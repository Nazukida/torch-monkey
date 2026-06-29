import { ChildProcess, spawn } from 'child_process'
import path from 'path'
import fs from 'fs'
import { app } from 'electron'

const DEFAULT_PORT = 19876

/** Where the AI pipeline runs. */
export type PythonMode = 'local' | 'remote'

export interface PythonManagerConfig {
  /** 'local' = spawn server.py here; 'remote' = talk to a server elsewhere. */
  mode?: PythonMode
  /** Local-mode port (default 19876). */
  port?: number
  /** Remote-mode base URL, e.g. http://127.0.0.1:19876 (SSH tunnel) or http://gpu-box:19876 (LAN). */
  remoteUrl?: string
}

/** Normalise a user-entered URL: ensure a scheme, drop trailing slashes. */
function normalizeUrl(url: string): string {
  let u = (url ?? '').trim()
  if (!u) return ''
  if (!/^https?:\/\//i.test(u)) u = `http://${u}`
  return u.replace(/\/+$/, '')
}

/**
 * Owns the Python FastAPI pipeline connection.
 *
 * Two modes:
 *  * **local** — spawn ``server.py`` as a child process (the historical
 *    behaviour). Polled at ``http://127.0.0.1:<port>`` until ready. Restarts
 *    on abnormal exit.
 *  * **remote** — the pipeline runs on another machine (typically a Linux GPU
 *    server), reached either through an SSH tunnel (``ssh -L
 *    19876:127.0.0.1:19876 …``, so the URL is still ``http://127.0.0.1:19876``)
 *    or over the LAN (server started with ``--host 0.0.0.0``). No local process
 *    is spawned — which is exactly what unblocks "the port forward didn't
 *    actually reach my computer": nothing local competes for the port and the
 *    request is allowed through.
 *
 * Designed to fail soft: if Python / models are missing (local) or the remote
 * endpoint is unreachable, the rest of the app still works — only the
 * video→motion capture feature is unavailable.
 */
export class PythonManager {
  private process: ChildProcess | null = null
  private _mode: PythonMode
  private _port: number
  private _remoteUrl: string
  private restarting = false
  private disposed = false

  constructor(cfg: PythonManagerConfig = {}) {
    this._mode = cfg.mode ?? 'local'
    this._port = cfg.port ?? DEFAULT_PORT
    this._remoteUrl = normalizeUrl(cfg.remoteUrl ?? '')
  }

  get mode(): PythonMode {
    return this._mode
  }
  get port(): number {
    return this._port
  }
  get remoteUrl(): string {
    return this._remoteUrl
  }

  /**
   * Whether capture endpoints may be attempted. Remote mode is usable as soon
   * as a URL is configured; local mode requires the spawned process. This
   * replaces the old hard ``isRunning`` gate that silently refused a perfectly
   * good SSH-tunnelled remote server.
   */
  get isUsable(): boolean {
    return this._mode === 'remote' ? this._remoteUrl.length > 0 : this.isRunning
  }

  /** True only when a LOCAL child process is alive. */
  get isRunning(): boolean {
    return this.process !== null && !this.process.killed
  }

  getBaseUrl(): string {
    if (this._mode === 'remote') return this._remoteUrl
    return `http://127.0.0.1:${this._port}`
  }

  /** Local-mode port (kept for the settings dialog / getConfig). */
  getPort(): number {
    return this._port
  }

  async start(): Promise<void> {
    if (this.disposed) return

    // Remote: the server lives elsewhere — nothing to spawn. Best-effort probe
    // so the health indicator flips green/red at startup; failure is non-fatal.
    if (this._mode === 'remote') {
      if (!this._remoteUrl) {
        console.warn('[PythonManager] remote mode selected but no URL set; capture disabled.')
        return
      }
      try {
        await this.waitForReady(8000)
      } catch (e) {
        console.warn('[PythonManager] remote server not reachable yet:', (e as Error).message)
      }
      return
    }

    if (this.process) return

    const serverPath = this.findServerPath()
    if (!serverPath) {
      console.warn('[PythonManager] server.py not found; capture feature disabled.')
      return
    }
    const pythonPath = this.findPython()
    if (!pythonPath) {
      console.warn('[PythonManager] No Python interpreter found; capture feature disabled.')
      return
    }

    this.process = spawn(
      pythonPath,
      ['-u', serverPath, '--port', String(this._port)],
      {
        env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true
      }
    )

    this.process.stdout?.on('data', (d: Buffer) => console.log(`[Python] ${d.toString().trimEnd()}`))
    this.process.stderr?.on('data', (d: Buffer) =>
      console.error(`[Python:err] ${d.toString().trimEnd()}`)
    )
    this.process.on('exit', (code) => {
      console.log(`[PythonManager] process exited code=${code}`)
      this.process = null
      // Only auto-restart a LOCAL child. In remote mode there is no local
      // process to revive (and this handler also fires once during a
      // local->remote teardown), so bail to avoid a stray restart timer.
      if (!this.disposed && code !== 0 && !this.restarting && this._mode === 'local') {
        this.restarting = true
        setTimeout(() => {
          this.restarting = false
          this.start().catch(() => undefined)
        }, 3000)
      }
    })

    try {
      await this.waitForReady(60000)
    } catch (e) {
      console.warn('[PythonManager] server did not become ready in time:', (e as Error).message)
    }
  }

  /**
   * Switch mode / URL / port at runtime (from the settings dialog's "Save &
   * apply"), without restarting the app. Stops any local child when leaving
   * local mode; spawns one when entering it.
   */
  async reconfigure(cfg: PythonManagerConfig): Promise<void> {
    const nextMode: PythonMode = cfg.mode ?? this._mode
    const nextPort = cfg.port ?? this._port
    const nextUrl = normalizeUrl(cfg.remoteUrl ?? '')
    const modeChanged = nextMode !== this._mode
    // A LOCAL-mode port change must restart the child: it was spawned with
    // --port <oldPort>, so without a restart getBaseUrl() would point at a port
    // nothing is listening on. A URL-only change in remote mode just flows
    // through getBaseUrl() with no process work.
    const localPortChanged =
      !modeChanged && this._mode === 'local' && nextPort !== this._port

    this._mode = nextMode
    this._port = nextPort
    this._remoteUrl = nextUrl

    if (localPortChanged) {
      await this.killProcess()
      await this.start()
      return
    }

    if (!modeChanged) {
      // Same mode, same port: nothing to (re)spawn. URL is read live via getBaseUrl().
      return
    }

    if (nextMode === 'remote') {
      // Leaving local: tear down the child so it can't fight the tunnel for the port.
      await this.killProcess()
      // Best-effort reachability probe of the new endpoint.
      if (nextUrl) {
        try {
          await this.waitForReady(8000)
        } catch (e) {
          console.warn('[PythonManager] remote not reachable after switch:', (e as Error).message)
        }
      }
    } else {
      // Entering local: make sure a child is running (idempotent).
      await this.start()
    }
  }

  private findServerPath(): string | null {
    const candidates = [
      path.join(app.getAppPath(), 'python', 'server.py'),
      path.join(process.resourcesPath ?? '', 'python', 'server.py'),
      path.join(__dirname, '..', '..', 'python', 'server.py'),
      path.join(process.cwd(), 'python', 'server.py')
    ]
    for (const c of candidates) {
      try {
        if (fs.existsSync(c)) return c
      } catch {
        /* ignore */
      }
    }
    return null
  }

  private findPython(): string | null {
    // 1. Bundled interpreter (packaged app)
    const bundledWin = path.join(process.resourcesPath ?? '', 'python', 'python.exe')
    try {
      if (process.platform === 'win32' && fs.existsSync(bundledWin)) return bundledWin
    } catch {
      /* ignore */
    }
    // 2. A project-local venv
    const localVenv =
      process.platform === 'win32'
        ? path.join(process.cwd(), 'python', '.venv', 'Scripts', 'python.exe')
        : path.join(process.cwd(), 'python', '.venv', 'bin', 'python')
    try {
      if (fs.existsSync(localVenv)) return localVenv
    } catch {
      /* ignore */
    }
    // 3. System PATH
    return process.platform === 'win32' ? 'python' : 'python3'
  }

  private async waitForReady(timeoutMs: number): Promise<void> {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      try {
        const res = await fetch(`${this.getBaseUrl()}/api/health`)
        if (res.ok) return
      } catch {
        /* not ready yet */
      }
      await new Promise((r) => setTimeout(r, 500))
    }
    throw new Error(`Python server not ready within ${timeoutMs}ms`)
  }

  private async killProcess(): Promise<void> {
    const proc = this.process
    if (!proc) return
    try {
      proc.kill('SIGTERM')
    } catch {
      /* ignore */
    }
    await new Promise((r) => setTimeout(r, 1000))
    if (this.process) {
      try {
        this.process.kill('SIGKILL')
      } catch {
        /* ignore */
      }
    }
    this.process = null
  }

  async stop(): Promise<void> {
    this.disposed = true
    await this.killProcess()
  }
}
