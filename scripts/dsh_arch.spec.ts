import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * The Python arch resolver is the single source of truth for every native
 * artifact directory the Termux install writes. These tests pin the contract
 * node-pty actually depends on: `prebuilds/<platform>-<process.arch>`.
 */

const RESOLVER = fileURLToPath(new URL('./dsh_arch.py', import.meta.url))
const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url))

interface Target {
  node_arch: string
  prebuild_dir: string
  cache_dir_name: string
  ndk_abi: string
  elf_machine: number
  elf_class: number
}

function resolve(arch?: string): Target {
  const args = [RESOLVER, '--json', ...(arch === undefined ? [] : [arch])]
  const result = spawnSync('python3', args, { encoding: 'utf8' })
  expect(result.error).toBeUndefined()
  expect(result.status).toBe(0)
  // The resolver emits exactly this record; `elf_machine` and `elf_class`
  // arrive as JSON numbers, so the declared type is what it reports rather than
  // a string map the fields would all have to be coerced out of.
  const parsed = JSON.parse(result.stdout) as Target
  return parsed
}

/**
 * Restate node-pty's resolver so a change to our mapping that stops matching it
 * fails here rather than on a device.
 * @param platform - `process.platform` value, e.g. `android`.
 * @param arch - `process.arch` value, e.g. `arm64`.
 * @returns The prebuilds directory name node-pty searches.
 */
function nodePtyPrebuildDir(platform: string, arch: string): string {
  return `prebuilds/${platform}-${arch}`
}

describe('dsh_arch target mapping', () => {
  it.each([
    ['arm', 'android-arm', 'armeabi-v7a'],
    ['arm64', 'android-arm64', 'arm64-v8a'],
    ['x86_64', 'android-x64', 'x86_64'],
  ])('maps %s to %s', (arch, prebuildDir, ndkAbi) => {
    const target = resolve(arch)
    expect(target.prebuild_dir).toBe(prebuildDir)
    expect(target.cache_dir_name).toBe(prebuildDir)
    expect(target.ndk_abi).toBe(ndkAbi)
  })

  it.each([
    ['aarch64', 'arm64'],
    ['arm64', 'arm64'],
    ['armv8l', 'arm'],
    ['armv7l', 'arm'],
    ['armv8a', 'arm'],
    ['arm', 'arm'],
    ['amd64', 'x64'],
    ['x86_64', 'x64'],
    ['i686', 'ia32'],
  ])('normalizes uname -m value %s to node arch %s', (unameMachine, nodeArch) => {
    expect(resolve(unameMachine).node_arch).toBe(nodeArch)
  })

  it('maps the 32-bit userland on 64-bit silicon to arm, not arm64', () => {
    // This device's `uname -m` is armv8l with a 32-bit Termux userland; Node
    // reports process.arch === 'arm' and dlopens only 32-bit binaries.
    expect(resolve('armv8l').node_arch).toBe('arm')
    expect(resolve('armv8l').prebuild_dir).toBe('android-arm')
  })

  it('agrees with the directory name node-pty searches', () => {
    for (const arch of ['arm', 'arm64', 'x64']) {
      const target = resolve(arch)
      expect(nodePtyPrebuildDir('android', target.node_arch)).toBe(`prebuilds/${target.prebuild_dir}`)
    }
  })

  it('reports the running device without an argument', () => {
    const reported = resolve()
    const expected = spawnSync('node', ['-p', 'process.arch'], { encoding: 'utf8' }).stdout.trim()
    expect(reported.node_arch).toBe(expected)
  })

  it('rejects an unknown architecture with a nonzero exit', () => {
    const result = spawnSync('python3', [RESOLVER, 'sparc64'], { encoding: 'utf8' })
    expect(result.status).toBe(2)
    expect(result.stderr).toContain('unsupported architecture')
  })
})

describe('dsh_arch ELF identity', () => {
  /**
   * Build a minimal ELF header with the given class and machine.
   * @param elfClass - `EI_CLASS`, 1 for 32-bit and 2 for 64-bit.
   * @param machine - `e_machine` value.
   * @returns The first 20 bytes of a little-endian ELF header.
   */
  function header(elfClass: 1 | 2, machine: number): Buffer {
    const bytes = Buffer.alloc(20)
    bytes.write('\x7fELF', 0, 'binary')
    bytes[4] = elfClass
    bytes[5] = 1 // little-endian
    bytes[16] = 3 // ET_DYN
    bytes.writeUInt16LE(machine, 18)
    return bytes
  }

  it('accepts a 32-bit ARM header as arm', () => {
    const probe = header(1, 40)
    const result = spawnSync(
      'python3',
      ['-c', `import sys; sys.path.insert(0,'${REPO_ROOT}scripts'); import dsh_arch; print(dsh_arch.binary_matches(bytes.fromhex('${probe.toString('hex')}'),'arm'))`],
      { encoding: 'utf8' },
    )
    expect(result.stdout.trim()).toBe('True')
  })

  it('rejects a 32-bit ARM header as arm64', () => {
    const probe = header(1, 40)
    const result = spawnSync(
      'python3',
      ['-c', `import sys; sys.path.insert(0,'${REPO_ROOT}scripts'); import dsh_arch; print(dsh_arch.binary_matches(bytes.fromhex('${probe.toString('hex')}'),'arm64'))`],
      { encoding: 'utf8' },
    )
    expect(result.stdout.trim()).toBe('False')
  })

  it('matches the cached binary on this device against its actual ELF header', () => {
    // Reading the header, not the directory name, is what makes the architecture visible.
    const cached = '/data/data/com.termux/files/home/.dsh/native/android-arm64/pty.node'
    let probe: Buffer
    try {
      probe = readFileSync(cached).subarray(0, 20)
    } catch {
      return // Device without the cache; covered by the synthetic cases above.
    }
    expect(probe.subarray(0, 4).toString('binary')).toBe('\x7fELF')
    const is64 = probe[4] === 2
    const expectedArch = is64 ? 'arm64' : 'arm'
    const otherArch = is64 ? 'arm' : 'arm64'
    const matchesExpected = spawnSync(
      'python3',
      ['-c', `import sys; sys.path.insert(0,'${REPO_ROOT}scripts'); import dsh_arch; print(dsh_arch.binary_matches(bytes.fromhex('${probe.toString('hex')}'),'${expectedArch}'))`],
      { encoding: 'utf8' },
    )
    expect(matchesExpected.stdout.trim()).toBe('True')
    const matchesOther = spawnSync(
      'python3',
      ['-c', `import sys; sys.path.insert(0,'${REPO_ROOT}scripts'); import dsh_arch; print(dsh_arch.binary_matches(bytes.fromhex('${probe.toString('hex')}'),'${otherArch}'))`],
      { encoding: 'utf8' },
    )
    expect(matchesOther.stdout.trim()).toBe('False')
  })
})
