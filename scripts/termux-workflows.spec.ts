import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { load } from 'js-yaml'
import { describe, expect, it } from 'vitest'

/**
 * The node-pty prebuild workflow published a binary named `android-arm64` whose
 * architecture was never asserted, so a 32-bit build could ship under a 64-bit
 * name. These tests hold the workflow shape that prevents that: one matrix leg
 * per supported ABI, and an ELF assertion that fails the job.
 */

const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url))

interface WorkflowJob {
  'runs-on'?: string
  needs?: string | string[]
  strategy?: { matrix?: { include?: Record<string, string>[] } }
  steps?: { name?: string; run?: string }[]
}

interface Workflow {
  jobs: Record<string, WorkflowJob>
}

/**
 * Load a workflow document.
 * @param name - Workflow file name under `.github/workflows/`.
 * @returns The parsed workflow.
 */
function workflow(name: string): Workflow {
  return load(readFileSync(`${REPO_ROOT}.github/workflows/${name}`, 'utf8')) as Workflow
}

describe('build-termux-pty.yml', () => {
  const doc = workflow('build-termux-pty.yml')
  const matrix = doc.jobs.ndk?.strategy?.matrix?.include ?? []

  it('builds every Android ABI Node can report', () => {
    const arches = matrix.map((entry) => entry.node_arch).sort()
    // arm is the 32-bit userland on 64-bit silicon (uname reports armv8l);
    // arm64 is a 64-bit userland; x64 covers emulators and ChromeOS.
    expect(arches).toEqual(['arm', 'arm64', 'x64'])
  })

  it('maps each ABI to the NDK triple and node-gyp arch', () => {
    for (const entry of matrix) {
      expect(entry.clang_triple).toBeTruthy()
      expect(entry.node_gyp_arch).toBe(entry.node_arch)
      expect(entry.elf_class).toMatch(/^ELF(32|64)$/)
      expect(entry.elf_machine).toBeTruthy()
    }
  })

  it('declares 32-bit for the arm leg', () => {
    const arm = matrix.find((entry) => entry.node_arch === 'arm')
    expect(arm?.elf_class).toBe('ELF32')
    expect(arm?.clang_triple).toBe('armv7a-linux-androideabi')
  })

  it('asserts the ELF class and machine instead of printing them', () => {
    const verify = doc.jobs.ndk?.steps?.find((step) => step.name?.startsWith('Verify ELF'))
    expect(verify?.run).toContain('"$CLASS" = "${{ matrix.elf_class }}"')
    expect(verify?.run).toContain('matrix.elf_machine')
    // A non-matching machine must exit nonzero, not warn.
    expect(verify?.run).toMatch(/::error::ELF machine/)
  })
})

describe('ci-termux.yml', () => {
  const doc = workflow('ci-termux.yml')

  it('runs the Termux specs on pull requests', () => {
    const run = doc.jobs['arch-and-installer']?.steps?.map((step) => step.run ?? '').join('\n') ?? ''
    expect(run).toContain('scripts/dsh_arch.spec.ts')
    expect(run).toContain('scripts/patch-termux.spec.ts')
    expect(run).toContain('scripts/install-termux.spec.ts')
  })

  it('checks shell and Python syntax', () => {
    const run = doc.jobs['arch-and-installer']?.steps?.map((step) => step.run ?? '').join('\n') ?? ''
    expect(run).toContain('bash -n')
    expect(run).toContain('python3 -m py_compile')
  })
})
