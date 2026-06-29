import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron'
import type { ElectronAPI, ProgressEvent } from '@shared/types/electron'

/**
 * Secure bridge between the renderer and the main process. Every capability the
 * renderer needs is funneled through these explicitly-allowlisted IPC channels.
 */
const api: ElectronAPI = {
  platform: ipcRenderer.sendSync('app:platform') as NodeJS.Platform,
  versions: (ipcRenderer.sendSync('app:versions') as ElectronAPI['versions']) ?? {
    electron: '',
    node: '',
    chrome: ''
  },

  openFileDialog: (options) => ipcRenderer.invoke('dialog:openFile', options),
  saveFileDialog: (options) => ipcRenderer.invoke('dialog:saveFile', options),
  readFile: (filePath) => ipcRenderer.invoke('fs:readFile', filePath),
  writeFile: (filePath, data) => ipcRenderer.invoke('fs:writeFile', filePath, data),

  getAppPath: (name) => ipcRenderer.invoke('app:getPath', name),

  dbCreateMotion: (data) => ipcRenderer.invoke('db:createMotion', data),
  dbGetMotion: (id) => ipcRenderer.invoke('db:getMotion', id),
  dbListMotions: (options) => ipcRenderer.invoke('db:listMotions', options),
  dbUpdateMotion: (id, partial) => ipcRenderer.invoke('db:updateMotion', id, partial),
  dbDeleteMotion: (id) => ipcRenderer.invoke('db:deleteMotion', id),
  dbGetPopularTags: (limit) => ipcRenderer.invoke('db:getPopularTags', limit),

  dbSaveProject: (data) => ipcRenderer.invoke('db:saveProject', data),
  dbGetProject: (id) => ipcRenderer.invoke('db:getProject', id),
  dbListProjects: () => ipcRenderer.invoke('db:listProjects'),

  dbGetSetting: (key) => ipcRenderer.invoke('db:getSetting', key),
  dbSetSetting: (key, value) => ipcRenderer.invoke('db:setSetting', key, value),
  dbGetStats: () => ipcRenderer.invoke('db:getStats'),

  projectSaveAs: (data) => ipcRenderer.invoke('project:saveAs', data),
  projectOpen: () => ipcRenderer.invoke('project:open'),

  pythonHealth: () => ipcRenderer.invoke('python:health'),
  pythonGetConfig: () => ipcRenderer.invoke('python:getConfig'),
  pythonConfigure: (cfg) => ipcRenderer.invoke('python:configure', cfg),
  pythonTestConnection: (url) => ipcRenderer.invoke('python:testConnection', url),
  previewVideo: (filePath) => ipcRenderer.invoke('python:previewVideo', filePath),
  processVideo: (filePath, options) =>
    ipcRenderer.invoke('python:processVideo', filePath, options),

  previewBilibili: (bvid, page) => ipcRenderer.invoke('python:previewBilibili', bvid, page),
  processBilibili: (bvid, options) =>
    ipcRenderer.invoke('python:processBilibili', bvid, options),

  onProgress: (callback: (e: ProgressEvent) => void) => {
    const listener = (_e: IpcRendererEvent, payload: ProgressEvent) => callback(payload)
    ipcRenderer.on('pipeline:progress', listener)
    return () => ipcRenderer.removeListener('pipeline:progress', listener)
  },

  onMenu: (callback: (action: string) => void) => {
    const listener = (_e: IpcRendererEvent, action: string) => callback(action)
    ipcRenderer.on('menu:newProject', () => callback('newProject'))
    ipcRenderer.on('menu:openProject', () => callback('openProject'))
    ipcRenderer.on('menu:saveProject', () => callback('saveProject'))
    ipcRenderer.on('menu:saveProjectAs', () => callback('saveProjectAs'))
    ipcRenderer.on('menu:importVideo', () => callback('importVideo'))
    ipcRenderer.on('menu:about', () => callback('about'))
    return () => {
      void listener
      ipcRenderer.removeAllListeners('menu:newProject')
      ipcRenderer.removeAllListeners('menu:openProject')
      ipcRenderer.removeAllListeners('menu:saveProject')
      ipcRenderer.removeAllListeners('menu:saveProjectAs')
      ipcRenderer.removeAllListeners('menu:importVideo')
      ipcRenderer.removeAllListeners('menu:about')
    }
  }
}

contextBridge.exposeInMainWorld('electronAPI', api)
