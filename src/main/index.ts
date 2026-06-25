import { app, BrowserWindow, shell, Menu, ipcMain, dialog } from 'electron'
import path from 'path'
import fs from 'fs'
import { DatabaseHandler } from './ipc/database-handler'
import { PythonManager } from './services/python-manager'
import { ProjectHandler } from './services/project-handler'
import type {
  VideoProcessOptions,
  VideoProcessResult,
  VideoInfo,
  BilibiliProcessOptions,
  BilibiliSource
} from '@shared/types/electron'
import type { ListMotionsOptions } from '@shared/types/motion'
import type { ProjectFile } from '@shared/types/project'

let mainWindow: BrowserWindow | null = null
let db: DatabaseHandler | null = null
let python: PythonManager
let projects: ProjectHandler

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1600,
    height: 900,
    minWidth: 1280,
    minHeight: 720,
    backgroundColor: '#050507',
    title: 'Torch Monkey',
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  win.on('ready-to-show', () => win.show())

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // electron-vite dev injects ELECTRON_RENDERER_URL; prod loads the built file.
  if (process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  return win
}

function registerSyncInfo(): void {
  ipcMain.on('app:platform', (e) => {
    e.returnValue = process.platform
  })
  ipcMain.on('app:versions', (e) => {
    e.returnValue = {
      electron: process.versions.electron,
      node: process.versions.node,
      chrome: process.versions.chrome
    }
  })
}

function registerDialogs(): void {
  ipcMain.handle('dialog:openFile', async (_e, options) => {
    const win = BrowserWindow.getFocusedWindow() ?? undefined
    const res = await dialog.showOpenDialog(win!, {
      properties: options?.multiSelections ? ['openFile', 'multiSelections'] : ['openFile'],
      title: options?.title,
      filters: options?.filters
    })
    return { canceled: res.canceled, filePaths: res.filePaths }
  })

  ipcMain.handle('dialog:saveFile', async (_e, options) => {
    const win = BrowserWindow.getFocusedWindow() ?? undefined
    const res = await dialog.showSaveDialog(win!, {
      title: options?.title,
      defaultPath: options?.defaultPath,
      filters: options?.filters
    })
    return { canceled: res.canceled, filePaths: res.filePath ? [res.filePath] : [] }
  })

  ipcMain.handle('fs:readFile', async (_e, filePath: string) => {
    try {
      const buf = await fs.promises.readFile(filePath)
      return { data: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) }
    } catch (e) {
      return { data: new ArrayBuffer(0), error: (e as Error).message }
    }
  })

  ipcMain.handle('fs:writeFile', async (_e, filePath: string, data: ArrayBuffer | string) => {
    try {
      const buf = typeof data === 'string' ? Buffer.from(data, 'utf-8') : Buffer.from(data)
      await fs.promises.writeFile(filePath, buf)
      return {}
    } catch (e) {
      return { error: (e as Error).message }
    }
  })

  ipcMain.handle('app:getPath', (_e, name) => app.getPath(name))
}

function registerDatabase(): void {
  ipcMain.handle('db:createMotion', (_e, data) => {
    db!.createMotion(data)
    return {}
  })
  ipcMain.handle('db:getMotion', (_e, id) => db!.getMotion(id))
  ipcMain.handle('db:listMotions', (_e, opts: ListMotionsOptions) => db!.listMotions(opts))
  ipcMain.handle('db:updateMotion', (_e, id, partial) => {
    db!.updateMotion(id, partial)
    return {}
  })
  ipcMain.handle('db:deleteMotion', (_e, id) => {
    db!.deleteMotion(id)
    return {}
  })
  ipcMain.handle('db:getPopularTags', (_e, limit) => db!.getPopularTags(limit))

  ipcMain.handle('db:saveProject', (_e, data: ProjectFile) => {
    db!.saveProject(data)
    return {}
  })
  ipcMain.handle('db:getProject', (_e, id) => db!.getProject(id))
  ipcMain.handle('db:listProjects', () => db!.listProjects())

  ipcMain.handle('db:getSetting', (_e, key) => db!.getSetting(key))
  ipcMain.handle('db:setSetting', (_e, key, value) => {
    db!.setSetting(key, value)
  })
  ipcMain.handle('db:getStats', () => db!.getStats())
}

function registerProjects(): void {
  ipcMain.handle('project:saveAs', (_e, data: ProjectFile) => projects.saveAs(data))
  ipcMain.handle('project:open', () => projects.open())
}

function sendProgress(phase: VideoProcessResult['status'] | string, progress: number, message?: string): void {
  mainWindow?.webContents.send('pipeline:progress', {
    taskId: 'current',
    phase: phase as 'frames' | 'pose2d' | 'pose3d' | 'optimize' | 'export' | 'done' | 'error',
    progress,
    message
  })
}

/** Normalize a pipeline JSON response (snake_case server → camelCase renderer). */
function normalizeProcessResult(
  raw: Record<string, unknown>
): VideoProcessResult & { source?: BilibiliSource } {
  return {
    taskId: (raw.task_id as string) ?? (raw.taskId as string) ?? '',
    status: ((raw.status as string) ?? 'failed') as VideoProcessResult['status'],
    motionData: (raw.motion_data ?? raw.motionData ?? null) as VideoProcessResult['motionData'],
    error: raw.error as string | undefined,
    stats: (raw.stats ?? undefined) as VideoProcessResult['stats'],
    source: (raw.source ?? undefined) as BilibiliSource | undefined
  }
}

function registerPython(): void {
  ipcMain.handle('python:health', async () => {
    try {
      const res = await fetch(`${python.getBaseUrl()}/api/health`)
      if (!res.ok) return { status: 'down' as const }
      const json = (await res.json()) as { models?: { mediapipe: boolean; motionbert: boolean } }
      return { status: 'ok' as const, models: json.models }
    } catch {
      return { status: 'down' as const }
    }
  })

  ipcMain.handle('python:previewVideo', async (_e, filePath: string) => {
    try {
      const buffer = await fs.promises.readFile(filePath)
      const blob = new Blob([buffer])
      const form = new FormData()
      form.append('file', blob, path.basename(filePath))
      const res = await fetch(`${python.getBaseUrl()}/api/preview-video`, {
        method: 'POST',
        body: form
      })
      if (!res.ok) return { error: `HTTP ${res.status}` }
      const json = (await res.json()) as { info?: VideoInfo; error?: string }
      return { info: json.info, error: json.error }
    } catch (e) {
      return { error: (e as Error).message }
    }
  })

  ipcMain.handle(
    'python:processVideo',
    async (_e, filePath: string, options: VideoProcessOptions = {}) => {
      if (!python.isRunning) {
        return {
          taskId: '',
          status: 'failed',
          motionData: null,
          error: 'Python pipeline is not running'
        }
      }
      try {
        sendProgress('frames', 0.05, 'Uploading & extracting frames')
        const buffer = await fs.promises.readFile(filePath)
        const blob = new Blob([buffer])
        const form = new FormData()
        form.append('file', blob, path.basename(filePath))
        const params = new URLSearchParams()
        if (options.fps) params.set('fps', String(options.fps))
        if (options.smooth !== undefined) params.set('smooth', String(options.smooth))
        if (options.detectKime !== undefined) params.set('detect_kime', String(options.detectKime))

        const url = `${python.getBaseUrl()}/api/process-video${params.toString() ? `?${params}` : ''}`
        sendProgress('pose2d', 0.15, 'Running AI pipeline…')
        const res = await fetch(url, { method: 'POST', body: form })
        if (!res.ok) {
          const text = await res.text()
          return { taskId: '', status: 'failed', motionData: null, error: `HTTP ${res.status}: ${text}` }
        }
        // Normalize snake_case (server) → camelCase (renderer contract).
        const raw = (await res.json()) as Record<string, unknown>
        const json = normalizeProcessResult(raw)
        sendProgress('done', 1, 'Completed')
        return json
      } catch (e) {
        sendProgress('error', 0, (e as Error).message)
        return {
          taskId: '',
          status: 'failed',
          motionData: null,
          error: (e as Error).message
        }
      }
    }
  )

  // ---- Bilibili (BV 号) capture: probe metadata, then download + run pipeline.
  ipcMain.handle(
    'python:previewBilibili',
    async (_e, bvid: string, page?: number) => {
      if (!python.isRunning) return { error: 'Python pipeline is not running' }
      try {
        const res = await fetch(`${python.getBaseUrl()}/api/preview-bilibili`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bvid, page: page ?? null })
        })
        if (!res.ok) {
          const text = await res.text()
          return { error: `HTTP ${res.status}: ${text}` }
        }
        return (await res.json()) as { ok?: boolean; info?: unknown; error?: string }
      } catch (e) {
        return { error: (e as Error).message }
      }
    }
  )

  ipcMain.handle(
    'python:processBilibili',
    async (_e, bvid: string, options: BilibiliProcessOptions = {}) => {
      if (!python.isRunning) {
        return {
          taskId: '',
          status: 'failed',
          motionData: null,
          error: 'Python pipeline is not running'
        }
      }
      try {
        sendProgress('frames', 0.02, `Downloading Bilibili ${bvid}…`)
        const res = await fetch(`${python.getBaseUrl()}/api/process-bilibili`, {
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
        if (!res.ok) {
          const text = await res.text()
          return { taskId: '', status: 'failed', motionData: null, error: `HTTP ${res.status}: ${text}` }
        }
        const raw = (await res.json()) as Record<string, unknown>
        const json = normalizeProcessResult(raw)
        sendProgress('done', 1, 'Completed')
        return json
      } catch (e) {
        sendProgress('error', 0, (e as Error).message)
        return {
          taskId: '',
          status: 'failed',
          motionData: null,
          error: (e as Error).message
        }
      }
    }
  )
}

function buildMenu(): Menu {
  const isMac = process.platform === 'darwin'
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? ([{ role: 'appMenu' }] as Electron.MenuItemConstructorOptions[])
      : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'New Project',
          accelerator: 'CmdOrCtrl+N',
          click: () => mainWindow?.webContents.send('menu:newProject')
        },
        {
          label: 'Open Project…',
          accelerator: 'CmdOrCtrl+O',
          click: () => mainWindow?.webContents.send('menu:openProject')
        },
        { type: 'separator' },
        {
          label: 'Save',
          accelerator: 'CmdOrCtrl+S',
          click: () => mainWindow?.webContents.send('menu:saveProject')
        },
        {
          label: 'Save As…',
          accelerator: 'CmdOrCtrl+Shift+S',
          click: () => mainWindow?.webContents.send('menu:saveProjectAs')
        },
        { type: 'separator' },
        {
          label: 'Import Video for Capture…',
          accelerator: 'CmdOrCtrl+I',
          click: () => mainWindow?.webContents.send('menu:importVideo')
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' }
      ]
    },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      role: 'help',
      submenu: [
        {
          label: 'Open User Data Folder',
          click: () => shell.openPath(app.getPath('userData'))
        },
        { label: 'About Torch Monkey', click: () => mainWindow?.webContents.send('menu:about') }
      ]
    }
  ]
  return Menu.buildFromTemplate(template)
}

app.whenReady().then(async () => {
  db = new DatabaseHandler()
  projects = new ProjectHandler()
  const portStr = db.getSetting('python_port')
  const port = portStr ? Number(JSON.parse(portStr)) : undefined
  python = new PythonManager(port)

  Menu.setApplicationMenu(buildMenu())

  registerSyncInfo()
  registerDialogs()
  registerDatabase()
  registerProjects()
  registerPython()

  mainWindow = createWindow()

  // Start the Python pipeline (non-fatal if it fails).
  python.start().catch((e) => console.warn('[main] python start failed:', e))

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', async (e) => {
  e.preventDefault()
  await python?.stop()
  db?.close()
  app.exit(0)
})
