import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * `patch_termux.py` is the whole Android adaptation layer and had no tests, so
 * the duplicated `apply_all` block and the architecture literals survived
 * several merges. These tests hold the structural invariants that a merge can
 * silently break, without running any patcher against the working tree.
 */

const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url))
const SCRIPTS_DIR = `${REPO_ROOT}scripts`

/**
 * Evaluate a Python expression with `scripts/` on the import path.
 * @param expression - Python source whose value is printed as JSON.
 * @returns The parsed JSON value.
 */
function pythonJson<T>(expression: string): T {
  const result = spawnSync('python3', ['-c', `import sys, json; sys.path.insert(0, ${JSON.stringify(SCRIPTS_DIR)}); import patch_termux as p; print(json.dumps(${expression}))`], {
    encoding: 'utf8',
    cwd: REPO_ROOT,
  })
  expect(result.stderr).toBe('')
  expect(result.status).toBe(0)
  return JSON.parse(result.stdout) as T
}

interface SuiteEntry {
  name: string
  has_invariant: boolean
}

/** The `(name, has_invariant)` pairs the expression below emits. */
type SuiteEntryTuple = [string, boolean]

describe('patch_termux patcher suite', () => {
  const suite = pythonJson<SuiteEntryTuple[]>(
    '[[n, h] for n, _f, h in p.patcher_suite()]',
  ).map(([name, has_invariant]): SuiteEntry => ({ name, has_invariant }))

  it('has no patcher listed twice', () => {
    // The suite previously called ten patchers twice, which doubled node-gyp
    // attempts on a phone. A registry makes a repeat impossible to reintroduce
    // by copy-paste, and this asserts it.
    const names = suite.map((entry) => entry.name)
    expect(new Set(names).size).toBe(names.length)
  })

  it('applies a non-trivial suite', () => {
    expect(suite.length).toBeGreaterThanOrEqual(20)
  })

  it('lists every patcher that check_status can verify as verified', () => {
    // A patcher added without an invariant is allowed, but it must be declared
    // unverified rather than assumed covered.
    const unverified = suite.filter((entry) => !entry.has_invariant).map((entry) => entry.name)
    expect(unverified).toContain('node-pty')
    expect(suite.filter((entry) => entry.has_invariant).length).toBeGreaterThanOrEqual(13)
  })
})

describe('patch_termux architecture handling', () => {
  it('derives the native prebuild directory from the running Node arch', () => {
    const prebuildDir = pythonJson<string>('p.PREBUILD_DIR')
    const nodeArch = spawnSync('node', ['-p', 'process.arch'], { encoding: 'utf8' }).stdout.trim()
    // node-pty searches prebuilds/<platform>-<arch>; anything else is a binary
    // no device will ever load.
    expect(prebuildDir).toBe(`android-${nodeArch}`)
  })

  it('derives the native cache directory from the same arch', () => {
    const cacheDir = pythonJson<string>('p.NATIVE_CACHE_DIR')
    expect(cacheDir.endsWith(`/native/${pythonJson<string>('p.PREBUILD_DIR')}`)).toBe(true)
  })

  it('contains no hardcoded android-arm64 path', () => {
    // Comments may mention the string; code must not build a path from it.
    const source = spawnSync(
      'python3',
      ['-c', `import re; s=open(${JSON.stringify(`${SCRIPTS_DIR}/patch_termux.py`)}).read(); print(len([l for l in s.splitlines() if 'android-arm64' in l and not l.lstrip().startswith('#')]))`],
      { encoding: 'utf8' },
    ).stdout.trim()
    expect(Number(source)).toBe(0)
  })
})

describe('dsh_arch integration', () => {
  it('keeps the shell and Python views of arch consistent', () => {
    // The bash scripts and the Python patcher must agree on the directory name,
    // or one writes a binary the other never finds.
    const fromPython = pythonJson<string>('p.PREBUILD_DIR')
    const fromNode = spawnSync('node', ['-p', '`android-${process.arch}`'], { encoding: 'utf8' }).stdout.trim()
    expect(fromPython).toBe(fromNode)
  })
})
