import fs from 'fs'
import path from 'path'
import { dialog, BrowserWindow } from 'electron'
import type { ProjectFile } from '@shared/types/project'

/**
 * .tmonkey project file IO. The format is plain JSON composing the four layers.
 */
export class ProjectHandler {
  async saveAs(data: ProjectFile): Promise<{ error?: string; path?: string }> {
    const win = BrowserWindow.getFocusedWindow() ?? undefined
    const result = await dialog.showSaveDialog(win!, {
      title: 'Save Torch Monkey Project',
      defaultPath: `${sanitize(data.metadata.name)}.tmonkey`,
      filters: [{ name: 'Torch Monkey Project', extensions: ['tmonkey'] }]
    })
    if (result.canceled || !result.filePath) return { error: 'canceled' }
    try {
      fs.writeFileSync(result.filePath, JSON.stringify(data, null, 2), 'utf-8')
      return { path: result.filePath }
    } catch (e) {
      return { error: (e as Error).message }
    }
  }

  async open(): Promise<{ data?: ProjectFile; error?: string; path?: string }> {
    const win = BrowserWindow.getFocusedWindow() ?? undefined
    const result = await dialog.showOpenDialog(win!, {
      title: 'Open Torch Monkey Project',
      properties: ['openFile'],
      filters: [{ name: 'Torch Monkey Project', extensions: ['tmonkey'] }]
    })
    if (result.canceled || result.filePaths.length === 0) return { error: 'canceled' }
    const filePath = result.filePaths[0]
    try {
      const raw = fs.readFileSync(filePath, 'utf-8')
      const data = JSON.parse(raw) as ProjectFile
      return { data, path: filePath }
    } catch (e) {
      return { error: (e as Error).message }
    }
  }

  readFileSync(filePath: string): Buffer {
    return fs.readFileSync(filePath)
  }
}

function sanitize(name: string): string {
  return (name || 'untitled').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 64)
}

export function fileExtension(p: string): string {
  return path.extname(p).toLowerCase()
}
