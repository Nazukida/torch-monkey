import { ChildProcess, spawn } from 'child_process'
import path from 'path'
import fs from 'fs'
import { app } from 'electron'

const DEFAULT_PORT = 19876

/**
 * Owns the Python FastAPI pipeline subprocess. Locates a usable Python
 * interpreter, spawns server.py, and polls /api/health until it is ready (or
 * times out). Restarts on abnormal exit. Designed to fail soft: if Python or
 * the models are missing, the rest of the app still works — only the
 * video→motion capture feature is unavailable.
 */
export class PythonManager {
  private process: ChildProcess | null = null
  private port: number = DEFAULT_PORT
  private restarting = false
  private disposed = false

  constructor(port?: number) {
    this.port = port ?? DEFAULT_PORT
  }

  getPort(): number {
    return this.port
  }

  getBaseUrl(): string {
    return `http://127.0.0.1:${this.port}`
  }

  get isRunning(): boolean {
    return this.process !== null && !this.process.killed
  }

  async start(): Promise<void> {
    if (this.process) return
    if (this.disposed) return

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
      ['-u', serverPath, '--port', String(this.port)],
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
      if (!this.disposed && code !== 0 && !this.restarting) {
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

  async stop(): Promise<void> {
    this.disposed = true
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
}
