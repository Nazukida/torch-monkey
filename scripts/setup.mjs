#!/usr/bin/env node
/**
 * Cross-platform dispatcher for the Torch Monkey environment setup.
 *
 * `npm run setup` works on Windows, Linux, and macOS: this script detects the
 * platform and shells out to setup.ps1 / setup.sh, forwarding all arguments
 * (e.g. `npm run setup -- --cpu` or `npm run setup -- --cuda 118`) verbatim.
 */
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { existsSync } from 'node:fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const forwarded = process.argv.slice(2)

const isWin = process.platform === 'win32'

let cmd, args
if (isWin) {
  const script = path.join(__dirname, 'setup.ps1')
  cmd = 'powershell'
  args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, ...forwarded]
} else {
  const script = path.join(__dirname, 'setup.sh')
  cmd = 'bash'
  args = [script, ...forwarded]
}

const target = path.join(__dirname, isWin ? 'setup.ps1' : 'setup.sh')
if (!existsSync(target)) {
  console.error(`[setup] missing ${target}`)
  process.exit(1)
}

const child = spawn(cmd, args, { stdio: 'inherit' })
child.on('error', (err) => {
  console.error(`[setup] failed to launch ${cmd}: ${err.message}`)
  process.exit(1)
})
child.on('exit', (code) => process.exit(code ?? 1))
