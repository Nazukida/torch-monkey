/**
 * Bridge contract exposed by the preload script (contextBridge) and consumed by
 * the renderer via `window.electronAPI`. Main-process IPC handlers must match.
 */
import type {
  MotionData,
  MotionMeta,
  ListMotionsOptions,
  ListMotionsResult
} from './motion'
import type { ProjectFile } from './project'

export interface OpenDialogOptions {
  title?: string
  filters?: { name: string; extensions: string[] }[]
  multiSelections?: boolean
}

export interface SaveDialogOptions {
  title?: string
  defaultPath?: string
  filters?: { name: string; extensions: string[] }[]
}

export interface FileDialogResult {
  canceled: boolean
  filePaths: string[]
}

export interface VideoProcessOptions {
  fps?: number
  smooth?: boolean
  detectKime?: boolean
}

/** Options for Bilibili (BV 号) capture. `page` selects a multi-part (P) index. */
export interface BilibiliProcessOptions extends VideoProcessOptions {
  page?: number
}

/** Metadata describing a resolved Bilibili video (probe or post-download). */
export interface BilibiliVideoInfo {
  bvid: string
  url: string
  title: string
  uploader?: string
  duration: number
  page: number
}

/** Source provenance attached to a Bilibili-captured motion. */
export interface BilibiliSource {
  bvid: string
  title: string
  duration: number
  url: string
  page: number
}

export interface VideoProcessResult {
  taskId: string
  status: 'completed' | 'failed'
  motionData: MotionData | null
  error?: string
  stats?: {
    frameCount: number
    durationSeconds: number
    kimeCount: number
  }
}

export interface VideoInfo {
  width: number
  height: number
  fps: number
  duration: number
  codec: string
  bitrate: number
}

export interface ProjectListItem {
  id: string
  name: string
  thumbnail?: string
  updatedAt: string
}

export interface ProgressEvent {
  taskId: string
  phase: 'frames' | 'pose2d' | 'pose3d' | 'optimize' | 'export' | 'done' | 'error'
  progress: number // 0..1
  message?: string
}

export interface ElectronAPI {
  platform: NodeJS.Platform
  versions: { electron: string; node: string; chrome: string }

  // ---- File dialogs ----
  openFileDialog: (options?: OpenDialogOptions) => Promise<FileDialogResult>
  saveFileDialog: (options?: SaveDialogOptions) => Promise<FileDialogResult>
  readFile: (filePath: string) => Promise<{ data: ArrayBuffer; error?: string }>
  writeFile: (filePath: string, data: ArrayBuffer | string) => Promise<{ error?: string }>

  // ---- App paths ----
  getAppPath: (name: 'userData' | 'appData' | 'documents' | 'temp') => Promise<string>

  // ---- Database: motions ----
  dbCreateMotion: (data: MotionData) => Promise<{ error?: string }>
  dbGetMotion: (id: string) => Promise<MotionData | null>
  dbListMotions: (options?: ListMotionsOptions) => Promise<ListMotionsResult>
  dbUpdateMotion: (id: string, partial: Partial<MotionData>) => Promise<{ error?: string }>
  dbDeleteMotion: (id: string) => Promise<{ error?: string }>
  dbGetPopularTags: (limit?: number) => Promise<{ name: string; count: number }[]>

  // ---- Database: projects ----
  dbSaveProject: (data: ProjectFile) => Promise<{ error?: string }>
  dbGetProject: (id: string) => Promise<ProjectFile | null>
  dbListProjects: () => Promise<ProjectListItem[]>

  // ---- Database: settings & stats ----
  dbGetSetting: (key: string) => Promise<string | null>
  dbSetSetting: (key: string, value: string) => Promise<void>
  dbGetStats: () => Promise<{
    motionCount: number
    projectCount: number
    totalStorageBytes: number
  }>

  // ---- Project files (.tmonkey) ----
  projectSaveAs: (data: ProjectFile) => Promise<{ error?: string; path?: string }>
  projectOpen: () => Promise<{ data?: ProjectFile; error?: string; path?: string }>

  // ---- Python AI pipeline ----
  pythonHealth: () => Promise<{
    status: 'ok' | 'down'
    models?: { mediapipe: boolean; motionbert: boolean }
  }>
  previewVideo: (filePath: string) => Promise<{ info?: VideoInfo; error?: string }>
  processVideo: (
    filePath: string,
    options?: VideoProcessOptions
  ) => Promise<VideoProcessResult>

  // ---- Bilibili (BV 号) capture ----
  previewBilibili: (
    bvid: string,
    page?: number
  ) => Promise<{ info?: BilibiliVideoInfo; error?: string }>
  processBilibili: (
    bvid: string,
    options?: BilibiliProcessOptions
  ) => Promise<VideoProcessResult & { source?: BilibiliSource }>

  // ---- Progress events (main -> renderer) ----
  onProgress: (callback: (e: ProgressEvent) => void) => () => void

  // ---- Application menu events (main -> renderer) ----
  onMenu: (callback: (action: string) => void) => () => void
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}
