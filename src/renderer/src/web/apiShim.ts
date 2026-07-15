/**
 * HTTP-backed implementation of the `ElectronAPI` contract for the browser.
 *
 * The renderer never imports Electron directly — every capability flows through
 * `window.electronAPI`, which the preload script injects under Electron. When
 * the renderer runs in a plain browser (no preload), `main.tsx` swaps in this
 * shim instead, so the same renderer codebase drives either backend:
 *
 *   Electron  → preload bridge → IPC → main process (SQLite + Python proxy)
 *   Browser   → this shim      → fetch → FastAPI server (SQLite + pipeline)
 *
 * The FastAPI server serves the built web bundle at "/", so the app and the API
 * share one origin and there are no CORS headaches for the normal same-origin
 * case. Pipeline call shapes mirror `src/main/index.ts` (the main process is
 * itself just an HTTP proxy for the Python server), including the coarse
 * progress markers emitted around each capture.
 */
import type {
  ElectronAPI,
  FileDialogResult,
  OpenDialogOptions,
  PythonConfig,
  PythonMode,
  ProgressEvent,
  PythonRuntime,
  VideoInfo,
  VideoProcessOptions,
  BilibiliProcessOptions,
  BilibiliVideoInfo,
  VideoProcessResult
} from '@shared/types/electron'
import type {
  ListMotionsOptions,
  ListMotionsResult,
  MotionData
} from '@shared/types/motion'
import type { ProjectFile } from '@shared/types/project'

// ---------------------------------------------------------------------------
// Pipeline base URL
// ---------------------------------------------------------------------------
const CFG_KEY = 'tm.pythonConfig'

/** Persisted connection config (the browser has no local Python/tunnel notion,
 * so this just remembers which server origin to talk to; defaults to the one
 * that served this page). */
function readConfig(): PythonConfig {
  try {
    const c = JSON.parse(localStorage.getItem(CFG_KEY) ?? '') as Partial<PythonConfig>
    if (c && c.remoteUrl) return { mode: 'remote', remoteUrl: c.remoteUrl, port: c.port ?? 19876 }
  } catch {
    /* ignore */
  }
  return { mode: 'remote', remoteUrl: location.origin, port: 19876 }
}

/** Origin to address the pipeline/store on. Defaults to the serving origin. */
function base(): string {
  return readConfig().remoteUrl.replace(/\/+$/, '')
}

// ---------------------------------------------------------------------------
// Picked-file registry (browser file dialog → in-memory token)
// ---------------------------------------------------------------------------
/**
 * Browsers have no absolute filesystem paths. `openFileDialog` stashes the
 * picked `File` under an opaque token and returns it; `processVideo` /
 * `readFile` redeem the token. The token only lives for the capturing user flow.
 */
const fileRegistry = new Map<string, File>()
let fileSeq = 0

function registerFile(file: File): string {
  const token = `blob:${++fileSeq}:${file.name}`
  fileRegistry.set(token, file)
  return token
}

function getFile(token: string): File | undefined {
  return fileRegistry.get(token)
}

function acceptFromFilters(filters?: OpenDialogOptions['filters']): string {
  return (filters ?? [])
    .flatMap((f) => f.extensions.map((ext) => (ext.includes('/') || ext.startsWith('.') ? ext : `.${ext}`)))
    .join(',')
}

/** Best-effort native file picker backed by a hidden <input type=file>. */
function pickFile(accept: string, multiple = false): Promise<FileDialogResult> {
  const input = document.createElement('input')
  input.type = 'file'
  if (accept) input.accept = accept
  if (multiple) input.multiple = true
  return new Promise<FileDialogResult>((resolve) => {
    let settled = false
    const done = (r: FileDialogResult) => {
      if (!settled) {
        settled = true
        resolve(r)
      }
    }
    input.addEventListener('change', () => {
      const files = Array.from(input.files ?? [])
      if (files.length === 0) {
        done({ canceled: true, filePaths: [] })
        return
      }
      done({ canceled: false, filePaths: files.map(registerFile) })
    })
    // No native cancel event exists; resolve as canceled when the window
    // regains focus without a selection.
    const onFocus = () => {
      window.removeEventListener('focus', onFocus)
      setTimeout(() => {
        if (!settled && (!input.files || input.files.length === 0)) {
          done({ canceled: true, filePaths: [] })
        }
      }, 300)
    }
    window.addEventListener('focus', onFocus)
    input.click()
  })
}

// ---------------------------------------------------------------------------
// Progress events
// ---------------------------------------------------------------------------
const progressCallbacks = new Set<(e: ProgressEvent) => void>()

function emitProgress(
  phase: ProgressEvent['phase'],
  progress: number,
  message?: string
): void {
  const e: ProgressEvent = { taskId: 'current', phase, progress, message }
  progressCallbacks.forEach((cb) => {
    try {
      cb(e)
    } catch {
      /* a bad listener must not break capture */
    }
  })
}

/** A pipeline task snapshot row from GET /api/tasks. */
interface RawTask {
  task_id: string
  status?: string
  progress?: number
  stage?: string | null
  message?: string | null
}

/** Map a server pipeline stage to the renderer's progress-phase vocabulary. */
function stageToPhase(stage: string | null | undefined): ProgressEvent['phase'] {
  switch (stage) {
    case 'pose_2d':
      return 'pose2d'
    case 'pose_3d':
      return 'pose3d'
    case 'optimize':
      return 'optimize'
    case 'export':
      return 'export'
    // 'download' (Bilibili), 'extract_frames', 'init', and anything unknown
    // all fall under the "frames" phase (getting/decoding the source video).
    default:
      return 'frames'
  }
}

/**
 * While a capture fetch is in flight, poll `/api/tasks` and re-emit the
 * server's finer-grained per-stage progress (download → extract → 2D → 3D →
 * optimize → export) — better than the coarse 3-step markers the Electron
 * path emits. The pipeline server runs a single worker, so we lock onto the
 * first running task we see and keep a monotonic high-water mark so progress
 * never goes backward. Returns a `stop()` to call when the fetch resolves.
 * Degrades gracefully (emits nothing) if the endpoint is unreachable or no
 * task is visible yet.
 */
function startProgressPolling(): () => void {
  let lockedId: string | null = null
  let high = 0
  let stopped = false
  let timer = 0
  const tick = async (): Promise<void> => {
    if (stopped) return
    try {
      const res = await fetch(`${base()}/api/tasks`)
      const j = (await res.json()) as { tasks?: RawTask[] }
      const tasks = j.tasks ?? []
      let t: RawTask | undefined = lockedId
        ? tasks.find((x) => x.task_id === lockedId)
        : undefined
      if (!t) {
        // Lock onto the first running/queued task (most recent, per /api/tasks sort).
        t = tasks.find((x) => x.status === 'running' || x.status === 'queued')
        if (t) lockedId = t.task_id
      }
      if (t && typeof t.progress === 'number' && t.progress >= high) {
        high = t.progress
        emitProgress(stageToPhase(t.stage), t.progress, t.message ?? undefined)
      }
    } catch {
      /* transient poll failure — retry next tick */
    }
    if (!stopped) timer = window.setTimeout(tick, 500)
  }
  timer = window.setTimeout(tick, 300) // first poll shortly after upload begins
  return () => {
    stopped = true
    if (timer) window.clearTimeout(timer)
  }
}

// ---------------------------------------------------------------------------
// Pipeline result normalisation (snake_case server → camelCase renderer)
// ---------------------------------------------------------------------------
function normalizeProcessResult(
  raw: Record<string, unknown>
): VideoProcessResult & { source?: unknown } {
  return {
    taskId: (raw.task_id as string) ?? (raw.taskId as string) ?? '',
    status: ((raw.status as string) ?? 'failed') as VideoProcessResult['status'],
    motionData: (raw.motion_data ?? raw.motionData ?? null) as MotionData | null,
    error: raw.error as string | undefined,
    stats: (raw.stats ?? undefined) as VideoProcessResult['stats'],
    source: raw.source ?? undefined
  }
}

function failedCapture(error: string): VideoProcessResult {
  return { taskId: '', status: 'failed', motionData: null, error }
}

// ---------------------------------------------------------------------------
// The ElectronAPI implementation
// ---------------------------------------------------------------------------
export const webAPI: ElectronAPI = {
  // -- sync info (unused by the renderer; harmless values) --
  platform: 'web' as unknown as ElectronAPI['platform'],
  versions: {
    electron: '',
    node: '',
    chrome: (navigator.userAgent.match(/Chrome\/([\d.]+)/)?.[1] ?? '') as string
  },

  // -- file dialogs --
  openFileDialog: (options) => pickFile(acceptFromFilters(options?.filters), options?.multiSelections),
  saveFileDialog: async () => ({ canceled: true, filePaths: [] }), // unused in renderer

  readFile: async (filePath) => {
    const file = getFile(filePath)
    if (!file) return { data: new ArrayBuffer(0), error: 'file not found' }
    return { data: await file.arrayBuffer() }
  },
  writeFile: async () => ({ error: 'writeFile not supported in browser' }),

  // -- app paths --
  getAppPath: async () => '',

  // -- motions --
  dbCreateMotion: async (data) => {
    await fetch(`${base()}/api/motions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
    return {}
  },
  dbGetMotion: async (id) => {
    const res = await fetch(`${base()}/api/motions/${encodeURIComponent(id)}`)
    if (!res.ok) return null
    return (await res.json()) as MotionData
  },
  dbListMotions: async (opts?: ListMotionsOptions): Promise<ListMotionsResult> => {
    const params = new URLSearchParams()
    if (opts?.search) params.set('search', opts.search)
    if (opts?.source) params.set('source', opts.source)
    if (opts?.tags?.length) params.set('tags', opts.tags.join(','))
    if (opts?.sortBy) params.set('sortBy', opts.sortBy)
    if (opts?.sortOrder) params.set('sortOrder', opts.sortOrder)
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.offset) params.set('offset', String(opts.offset))
    const res = await fetch(`${base()}/api/motions?${params.toString()}`)
    return (await res.json()) as ListMotionsResult
  },
  dbUpdateMotion: async (id, partial) => {
    await fetch(`${base()}/api/motions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(partial)
    })
    return {}
  },
  dbDeleteMotion: async (id) => {
    await fetch(`${base()}/api/motions/${encodeURIComponent(id)}`, { method: 'DELETE' })
    return {}
  },
  dbGetPopularTags: async (limit) => {
    const res = await fetch(`${base()}/api/tags?limit=${limit ?? 20}`)
    const j = (await res.json()) as { tags: { name: string; count: number }[] }
    return j.tags ?? []
  },

  // -- projects (DB mirror) --
  dbSaveProject: async (data) => {
    await fetch(`${base()}/api/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
    return {}
  },
  dbGetProject: async (id) => {
    const res = await fetch(`${base()}/api/projects/${encodeURIComponent(id)}`)
    if (!res.ok) return null
    return (await res.json()) as ProjectFile
  },
  dbListProjects: async () => {
    const res = await fetch(`${base()}/api/projects`)
    const j = (await res.json()) as { projects: { id: string; name: string; thumbnail?: string; updatedAt: string }[] }
    return j.projects ?? []
  },

  // -- settings & stats --
  dbGetSetting: async (key) => {
    const res = await fetch(`${base()}/api/settings/${encodeURIComponent(key)}`)
    const j = (await res.json()) as { value: string | null }
    return j.value
  },
  dbSetSetting: async (key, value) => {
    await fetch(`${base()}/api/settings/${encodeURIComponent(key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value })
    })
  },
  dbGetStats: async () => {
    const res = await fetch(`${base()}/api/stats`)
    return (await res.json()) as { motionCount: number; projectCount: number; totalStorageBytes: number }
  },

  // -- .tmonkey project file (browser download / upload) --
  projectSaveAs: async (data) => {
    try {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const safe = (data.metadata?.name || 'project').replace(/[^\w一-龥.-]+/g, '_')
      a.href = url
      a.download = `${safe}.tmonkey`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      return { path: a.download }
    } catch (e) {
      return { error: (e as Error).message }
    }
  },
  projectOpen: () =>
    new Promise((resolve) => {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = '.tmonkey,application/json'
      input.onchange = async () => {
        const f = input.files?.[0]
        if (!f) {
          resolve({ error: 'No file selected' })
          return
        }
        try {
          resolve({ data: JSON.parse(await f.text()) as ProjectFile, path: f.name })
        } catch (e) {
          resolve({ error: (e as Error).message })
        }
      }
      input.click()
    }),

  // -- Python AI pipeline --
  pythonHealth: async () => {
    const endpoint = { mode: 'remote' as PythonMode, baseUrl: base() }
    try {
      const res = await fetch(`${base()}/api/health`)
      if (!res.ok) return { status: 'down' as const, endpoint }
      const j = (await res.json()) as { models?: { mediapipe: boolean; motionbert: boolean }; runtime?: PythonRuntime }
      return { status: 'ok' as const, models: j.models, runtime: j.runtime, endpoint }
    } catch {
      return { status: 'down' as const, endpoint }
    }
  },
  pythonGetConfig: async () => readConfig(),
  pythonConfigure: async (cfg) => {
    const prev = readConfig()
    const next: PythonConfig = {
      mode: (cfg.mode ?? prev.mode) as PythonMode,
      remoteUrl: cfg.remoteUrl ?? prev.remoteUrl,
      port: cfg.port ?? prev.port
    }
    localStorage.setItem(CFG_KEY, JSON.stringify(next))
    return webAPI.pythonHealth()
  },
  pythonTestConnection: async (url) => {
    let target = (url ?? '').trim() || base() || location.origin
    if (!/^https?:\/\//i.test(target)) target = `http://${target}`
    target = target.replace(/\/+$/, '')
    const t0 = performance.now()
    try {
      const res = await fetch(`${target}/api/health`, { signal: AbortSignal.timeout(5000) })
      const latencyMs = Math.round(performance.now() - t0)
      if (!res.ok) return { ok: false as const, latencyMs, error: `HTTP ${res.status}` }
      const j = (await res.json()) as { models?: { mediapipe: boolean; motionbert: boolean }; runtime?: PythonRuntime }
      return { ok: true as const, latencyMs, models: j.models, runtime: j.runtime }
    } catch (e) {
      return { ok: false as const, latencyMs: Math.round(performance.now() - t0), error: (e as Error).message }
    }
  },
  previewVideo: async (filePath) => {
    const file = getFile(filePath)
    if (!file) return { error: 'file not found' }
    try {
      const form = new FormData()
      form.append('file', file, file.name)
      const res = await fetch(`${base()}/api/preview-video`, { method: 'POST', body: form })
      if (!res.ok) return { error: `HTTP ${res.status}: ${await res.text()}` }
      const j = (await res.json()) as { ok?: boolean; info?: VideoInfo; error?: string }
      return { info: j.info, error: j.error }
    } catch (e) {
      return { error: (e as Error).message }
    }
  },
  processVideo: async (filePath, options: VideoProcessOptions = {}) => {
    const file = getFile(filePath)
    if (!file) return failedCapture('file not found')
    const stop = startProgressPolling()
    try {
      emitProgress('frames', 0.05, 'Uploading & extracting frames')
      const form = new FormData()
      form.append('file', file, file.name)
      const params = new URLSearchParams()
      if (options.fps) params.set('fps', String(options.fps))
      if (options.smooth !== undefined) params.set('smooth', String(options.smooth))
      if (options.detectKime !== undefined) params.set('detect_kime', String(options.detectKime))
      const qs = params.toString()
      const res = await fetch(`${base()}/api/process-video${qs ? `?${qs}` : ''}`, {
        method: 'POST',
        body: form
      })
      if (!res.ok) return failedCapture(`HTTP ${res.status}: ${await res.text()}`)
      const json = normalizeProcessResult((await res.json()) as Record<string, unknown>)
      emitProgress('done', 1, 'Completed')
      return json
    } catch (e) {
      emitProgress('error', 0, (e as Error).message)
      return failedCapture((e as Error).message)
    } finally {
      stop()
    }
  },

  // -- Bilibili (BV 号) capture --
  previewBilibili: async (bvid, page) => {
    try {
      const res = await fetch(`${base()}/api/preview-bilibili`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bvid, page: page ?? null })
      })
      if (!res.ok) return { error: `HTTP ${res.status}: ${await res.text()}` }
      const j = (await res.json()) as { ok?: boolean; info?: BilibiliVideoInfo; error?: string }
      return { info: j.info, error: j.error }
    } catch (e) {
      return { error: (e as Error).message }
    }
  },
  processBilibili: async (bvid, options: BilibiliProcessOptions = {}) => {
    const stop = startProgressPolling()
    try {
      emitProgress('frames', 0.02, `Downloading Bilibili ${bvid}…`)
      const res = await fetch(`${base()}/api/process-bilibili`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bvid,
          page: options.page ?? null,
          fps: options.fps ?? 30,
          smooth: options.smooth ?? true,
          detect_kime: options.detectKime ?? true
        })
      })
      if (!res.ok) return failedCapture(`HTTP ${res.status}: ${await res.text()}`)
      const json = normalizeProcessResult((await res.json()) as Record<string, unknown>)
      emitProgress('done', 1, 'Completed')
      return json
    } catch (e) {
      emitProgress('error', 0, (e as Error).message)
      return failedCapture((e as Error).message)
    } finally {
      stop()
    }
  },

  // -- event streams --
  onProgress: (callback) => {
    progressCallbacks.add(callback)
    return () => {
      progressCallbacks.delete(callback)
    }
  },
  onMenu: () => () => {
    /* no native app menu in a browser; all actions are reachable via the TopBar */
  }
}
