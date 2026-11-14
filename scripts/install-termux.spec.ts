import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * The installer scripts cannot be executed end to end in CI without a device,
 * but the failures that broke real devices were structural: a non-empty check
 * standing in for a valid archive, an aarch64-only ELF gate, and a launcher
 * that disagreed with the installer that generated it. Those are assertable
 * from source.
 */

const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url))

/**
 * Read a repository file.
 * @param relativePath - Path relative to the repository root.
 * @returns The file contents.
 */
function read(relativePath: string): string {
  return readFileSync(`${REPO_ROOT}${relativePath}`, 'utf8')
}

describe('install-termux.sh archive handling', () => {
  const installer = read('scripts/install-termux.sh')

  it('validates the downloaded archive before extracting it', () => {
    // A failed transfer leaves a non-empty file, so `-s` alone accepted an
    // error page or a truncated body and fell through to a silent build. The
    // transfer now streams through download_with_progress, which integrity-
    // checks the part file with gzip -t; the extraction step then gates on
    // ARCHIVE_OK. Assert those, not the tar -tzf command that predated the
    // progress rewrite and now lives in dsh-update.sh.
    expect(installer).toContain('gzip -t "$part"')
    expect(installer).toContain('ARCHIVE_OK')
  })

  it('extracts to a staging directory instead of over the checkout', () => {
    expect(installer).toMatch(/EXTRACT_DIR=\$\(mktemp -d/)
    expect(installer).toContain('cp -R "$EXTRACT_DIR"/. "$DSH_DIR"/')
  })

  it('installs dependencies before attempting a local compile', () => {
    // The compile commands need tsx and friends, which arrive with pnpm
    // install; running the build first could only fail.
    const installAt = installer.indexOf('pnpm install --frozen-lockfile=false --ignore-scripts')
    const buildAt = installer.indexOf('pnpm run build:lib:host')
    expect(installAt).toBeGreaterThan(0)
    expect(buildAt).toBeGreaterThan(installAt)
  })

  it('fails loudly when neither the bundle nor the compile produced a launcher', () => {
    expect(installer).toMatch(/fail_and_dump "Deploy Build Artifacts/)
  })
})

describe('install-pty-prebuild.sh architecture handling', () => {
  const script = read('scripts/install-pty-prebuild.sh')

  it('derives the prebuild directory from the running Node arch', () => {
    expect(script).toContain('NODE_ARCH=$(node -p \'process.arch\'')
    expect(script).toContain('PREBUILD_DIR="android-${NODE_ARCH}"')
  })

  it('no longer rejects every non-aarch64 binary', () => {
    // The previous gate matched a `file` description against aarch64 and
    // exited 1 otherwise, which made the documented repair path unusable on
    // the 32-bit devices that needed it.
    expect(script).not.toMatch(/not an aarch64 shared object/)
    expect(script).toContain('dsh_arch.binary_matches')
  })

  it('does not depend on `file` being installed', () => {
    // `file` is not among the packages the installer installs, so the gate
    // must read the header itself.
    expect(script).toContain('od -An -tx1 -N20')
  })

  it('installs into the directory node-pty searches', () => {
    expect(script).toContain('prebuilds/$PREBUILD_DIR/pty.node')
  })
})

describe('launcher and installer agree on pnpm settings', () => {
  const installer = read('scripts/install-termux.sh')

  it('the generated launcher disables the package-manager version check', () => {
    // pnpm publishes no android-arm binary at any version, so the pinned
    // packageManager cannot resolve on a phone. Without these the plain script
    // warns and the failure surfaces on the first pnpm call dsh makes.
    const start = installer.indexOf("cat <<'LAUNCHER_EOF'")
    const end = installer.indexOf('\nLAUNCHER_EOF\n', start)
    expect(start).toBeGreaterThan(-1)
    expect(end).toBeGreaterThan(start)
    const launcher = installer.slice(start, end)
    expect(launcher).toContain('pnpm_config_pm_on_fail=ignore')
    expect(launcher).toContain('pnpm_config_manage_package_manager_versions=false')
    expect(launcher).toContain('COREPACK_ENABLE_AUTO_PIN=0')
  })
})

describe('Android sandbox default', () => {
  const bundle = read('packages/bundle/base/cordis.patch.yml')

  it('does not request a confined mode Android has no runner for', () => {
    // PLATFORM_CHAINS covers linux, darwin, and win32. A confined mode on
    // android fails closed on every command.
    expect(bundle).toMatch(/process\.platform === 'android' \? 'danger-full-access'/)
  })

  it('still honours an explicit DSH_PERMISSION_MODE override', () => {
    expect(bundle).toMatch(/process\.env\.DSH_PERMISSION_MODE \?\? \(process\.platform === 'android'/)
  })
})
