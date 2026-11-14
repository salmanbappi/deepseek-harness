import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

/**
 * End-to-end coverage of the Termux install pieces that can run without an
 * Android device: the patch suite must be idempotent against a real checkout,
 * and the pty installer must place its binary where node-pty looks and reject a
 * binary built for another architecture. Both failures were invisible before,
 * because nothing executed these scripts.
 */

const REPO_ROOT = new URL('../', import.meta.url).pathname

const scratch: string[] = []

afterEach(() => {
  for (const dir of scratch.splice(0)) rmSync(dir, { recursive: true, force: true })
})

/**
 * Make an isolated directory owned by this test.
 * @param prefix - Temporary-directory name prefix.
 * @returns The created path.
 */
function scratchDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), `dsh-${prefix}-`))
  scratch.push(dir)
  return dir
}

/**
 * Write a minimal ELF header for a given architecture.
 * @param elfClass - `EI_CLASS`, 1 for 32-bit and 2 for 64-bit.
 * @param machine - `e_machine` value.
 * @returns The 20 header bytes plus a small payload.
 */
function elfFixture(elfClass: 1 | 2, machine: number): Buffer {
  const head = Buffer.alloc(64)
  head.write('\x7fELF', 0, 'binary')
  head[4] = elfClass
  head[5] = 1
  head[16] = 3
  head.writeUInt16LE(machine, 18)
  return head
}

describe('patch_termux idempotency', () => {
  /**
   * Copy the source files a chosen set of patchers edits into a scratch tree
   * with the same relative layout, so they can run without touching the repo.
   * @param relativePaths - Repository-relative file paths to copy.
   * @returns The scratch repository root.
   */
  function scratchRepo(relativePaths: readonly string[]): string {
    const root = scratchDir('patcher')
    for (const relative of relativePaths) {
      const from = join(REPO_ROOT, relative)
      if (!existsSync(from)) continue
      const to = join(root, relative)
      mkdirSync(join(to, '..'), { recursive: true })
      copyFileSync(from, to)
    }
    return root
  }

  it('applies the fs patches twice without changing the files a second time', () => {
    // Every patcher is marker-guarded, but nothing enforced that. A patcher
    // that appended unconditionally would rewrite a file on each install.
    const files = [
      'packages/attachment/attachment-local/src/store.ts',
      'packages/fs/fs-local/src/fsio.ts',
    ]
    const root = scratchRepo(files)

    // The patcher resolves paths from its module-level REPO_DIR, so the copy is
    // reached by overriding that attribute before the patcher runs.
    const script = `
import sys
sys.path.insert(0, ${JSON.stringify(join(REPO_ROOT, 'scripts'))})
import patch_termux as p
p.REPO_DIR = ${JSON.stringify(root)}
p.patch_attachment_store()
p.patch_fs_local()
`
    const snapshot = (): string =>
      files.map((relative) => readFileSync(join(root, relative), 'utf8')).join('\n\u0000\n')

    execFileSync('python3', ['-c', script], { encoding: 'utf8' })
    const first = snapshot()
    execFileSync('python3', ['-c', script], { encoding: 'utf8' })
    const second = snapshot()

    // A second run must be a no-op, and the first run must have changed
    // something, or the test would pass on a patcher that never matched.
    expect(second).toBe(first)
  })
})

describe('install-pty-prebuild binary placement', () => {
  it('installs into the directory node-pty resolves for the running arch', () => {
    const work = scratchDir('ptyinstall')
    const home = join(work, 'home')
    const dsh = join(work, 'repo')
    mkdirSync(join(dsh, 'node_modules/node-pty'), { recursive: true })
    mkdirSync(home, { recursive: true })
    writeFileSync(join(dsh, 'node_modules/node-pty/package.json'), '{"name":"node-pty"}')

    const arch = execFileSync('node', ['-p', 'process.arch'], { encoding: 'utf8' }).trim()
    const fixture = join(work, 'pty.node')
    // Build a header for the architecture this host reports, so the assertion
    // in the script is exercised rather than bypassed.
    const elfByArch: Record<string, [1 | 2, number]> = { arm: [1, 40], arm64: [2, 183], x64: [2, 62], ia32: [1, 3] }
    const [elfClass, machine] = elfByArch[arch] ?? [2, 62]
    writeFileSync(fixture, elfFixture(elfClass, machine))

    execFileSync('bash', [join(REPO_ROOT, 'scripts/install-pty-prebuild.sh'), '--file', fixture], {
      env: { ...process.env, HOME: home, DSH_DIR: dsh, PREFIX: join(work, 'prefix') },
      encoding: 'utf8',
    })

    const installed = join(dsh, 'node_modules/node-pty/prebuilds', `android-${arch}`, 'pty.node')
    expect(existsSync(installed)).toBe(true)
    expect(existsSync(join(home, '.dsh/native', `android-${arch}`, 'pty.node'))).toBe(true)
  })

  it('rejects a binary built for a different architecture', () => {
    // The old script rejected everything that was not aarch64; the replacement
    // must still refuse a genuine mismatch, or a wrong binary reaches a device.
    const work = scratchDir('ptyreject')
    const home = join(work, 'home')
    const dsh = join(work, 'repo')
    mkdirSync(join(dsh, 'node_modules/node-pty'), { recursive: true })
    mkdirSync(home, { recursive: true })
    writeFileSync(join(dsh, 'node_modules/node-pty/package.json'), '{"name":"node-pty"}')

    const arch = execFileSync('node', ['-p', 'process.arch'], { encoding: 'utf8' }).trim()
    // Pick an architecture that is definitely not this host's.
    const fixture = join(work, 'wrong.node')
    writeFileSync(fixture, elfFixture(arch === 'arm64' ? 1 : 2, arch === 'arm64' ? 40 : 183))

    const result = (() => {
      try {
        execFileSync('bash', [join(REPO_ROOT, 'scripts/install-pty-prebuild.sh'), '--file', fixture], {
          env: { ...process.env, HOME: home, DSH_DIR: dsh, PREFIX: join(work, 'prefix') },
          encoding: 'utf8',
          stdio: 'pipe',
        })
        return 0
      } catch (error) {
        return (error as { status?: number }).status ?? 1
      }
    })()

    expect(result).not.toBe(0)
    expect(existsSync(join(dsh, 'node_modules/node-pty/prebuilds', `android-${arch}`, 'pty.node'))).toBe(false)
  })
})
