# dsh-mobile — plan

## Context

`~/dsh-mobile` is `SehonYT/dsh-termux` (v0.2.2-rc.1),
created 2026-11-13. Goal: make it install and run on every Android device, not just aarch64
Termux, and add the test and CI coverage that would have caught these failures.

The reported symptom — "arm64 devices also fail" — has a specific cause, found by reading
the code and inspecting the shipped binaries.

## Root cause

node-pty resolves its native library from a path built from the runtime identity
(`node-pty/lib/utils.js`):

```js
var dirs = ['build/Release', 'build/Debug', "prebuilds/".concat(process.platform, "-").concat(process.arch)];
```

The fork writes that binary to a **hardcoded** `prebuilds/android-arm64` in 91 places across
8 files. Nothing maps `process.arch` to that name. So:

| Device | Folder node-pty looks for | Folder fork writes | Shipped binary | Result |
|---|---|---|---|---|
| arm32 (`armv8l`, this phone) | `prebuilds/android-arm` | `android-arm64` | arm32 | **not found** — pty never loads |
| arm64 (modern phone) | `prebuilds/android-arm64` | `android-arm64` | arm32 (mislabeled) | **found, dlopen fails** — wrong arch |

Both fail. The 64-bit case fails at `dlopen` because the binary in the cache here is
`ELF 32-bit LSB, ARM, e_machine=40`, despite the directory being named `android-arm64`.

Contributing defects:

1. **Release tarball ships 0 native binaries.** `dsh-termux-prebuilt-v0.2.2-rc.1.tar.gz`
   has 6015 `lib/` files and zero `.node` files, so a fresh install always depends on the
   cache copy being correct.
2. **CI builds arm64 only.** `build-termux-pty.yml:76` `--arch=arm64`;
   `build-termux-sherpa.yml` likewise aarch64. No arm32 or x64 job.
3. **The arch verification step does not verify arch.** `build-termux-pty.yml:79-92` prints
   `readelf` output and only fails on `GLIBC_` imports. This is how a mislabeled binary
   reaches a release unnoticed.
4. **`install-pty-prebuild.sh:82-88` hard-rejects non-aarch64**, so the documented repair
   path is unusable on the 32-bit device that needs it most.
5. **`install-termux.sh:295`** treats any non-empty download as success (`[ -s ]`), so a
   truncated tarball passes and `tar -xzf … || true` fails silently.
6. **`apply_all()` runs 10 patchers twice** (`patch_termux.py`).
7. **21 patchers, 15 `--check` invariants.** `patch_node_pty`, `patch_fs_ext`, `patch_koffi`,
   `patch_ripgrep`, `patch_bundle_layer_cache`, `patch_fs_batch_edits` are unverified.
8. **`--check` asserts substrings, not behavior**, and `all_ok` is a hand-written 15-term
   boolean chain.
9. **Zero tests reference Termux** (`grep` across all `*.spec.ts`/`*.test.ts` → 0 hits).
10. **`speech-to-text-sensevoice` hardcodes `android-arm64`** in its supported list
    (`runtime.ts:56`), so local speech is unavailable on arm32.

## Approach

### Step 1 — One arch resolver, used everywhere

Add `scripts/dsh_arch.py` exporting:

```
resolve(target_arch=None, platform=None) -> {node_arch, prebuild_dir, cache_dir, ndk_abi, ci_artifact}
```

Mapping (the `prebuild_dir` values are dictated by node-pty's resolver, not by us):

| input | prebuild_dir | cache subdir | NDK ABI |
|---|---|---|---|
| arm64 / aarch64 | `android-arm64` | `android-arm64` | `arm64-v8a` |
| arm / armv7l / armv8l | `android-arm` | `android-arm` | `armeabi-v7a` |
| x64 / x86_64 | `android-x64` | `android-x64` | `x86_64` |

`armv8l` maps to arm32 (32-bit userland on 64-bit silicon). In bash, an equivalent
`scripts/lib/arch.sh` sourcing `node -p process.arch` with a `uname -m` fallback, so the
shell and Python sides cannot disagree.

Replace all 91 `android-arm64` literals with the resolver, except the two CI workflow
matrices (Step 3) which enumerate arches explicitly.

### Step 2 — Cache both arches, migrate the mislabeled one

`~/.dsh/native/<prebuild_dir>/pty.node`. Migrate an existing `android-arm64` binary only
after reading its ELF header and confirming `e_machine` matches the directory — do not trust
the folder name. This device's cache is arm32 and must move to `android-arm/`.

Add `scripts/lib/elf.sh` (the ELF class/machine check currently duplicated in
`install-pty-prebuild.sh` and the CI step) so the assertion is written once and is an actual
assertion.

### Step 3 — CI builds and verifies every arch

In `build-termux-pty.yml` and `build-termux-sherpa.yml`, add a `matrix.abi`
(`arm64-v8a`, `armeabi-v7a`, `x86_64`) and replace the print-only "verify" step with a gate:

- parse `readelf -h` and fail unless `Class` and `Machine` equal the matrix expectation
- keep the existing `GLIBC_` rejection
- name artifacts `pty-<prebuild_dir>` so download can select by arch

Publish all three per release. Pin the toolchain so a rebuild is reproducible.

### Step 4 — Make the install path fail visibly and recover

- `install-termux.sh`: download to `.part`, verify `content-length` and a published
  `sha256`, then rename. Retry with backoff. Remove `|| true` from the extract.
- Prefer curl when present (resumable, `--retry`), keep the Python progress bar as fallback.
- `install-pty-prebuild.sh`: accept any supported arch, select the artifact by
  `prebuild_dir`, and verify ELF against the running Node.
- `patch_termux.py`: drop the duplicated patcher calls; add `--check` coverage for the
  six unverified patchers; replace the hand-written `all_ok` chain with a list-driven
  result so a new check cannot be forgotten.

### Step 5 — Tests

House pattern is colocated `*.spec.ts` next to the source, vitest, `vi.mock` for fs
(`scripts/repo-files.spec.ts` is the template). Add:

- `scripts/dsh_arch.spec.ts` — table-driven over every `uname -m` / `process.arch` pair,
  including `armv8l` → `android-arm`. Assert `prebuild_dir` matches what node-pty's
  resolver would construct, with the resolver formula restated in the test so the two
  cannot drift.
- `scripts/patch-termux.spec.ts` — apply each patcher to a fixture tree; assert idempotency
  (twice = once), assert every patcher has a `--check` invariant, assert `apply_all` calls
  each patcher exactly once.
- `scripts/install-termux.spec.ts` — simulate truncated download, 404 body, rate-limit JSON,
  and a valid tarball; assert only the last proceeds.
- e2e: `scripts/e2e/install-devices.e2e.ts` — in a throwaway `$HOME`, run the patcher and
  `install-pty-prebuild.sh --file <fixture>` for each fixture arch and assert
  `node-pty` resolves. Fixtures are tiny stub `.node` files with correct ELF headers, so
  the test runs on any host without a real Android device.

### Step 6 — CI wiring

New `.github/workflows/ci-termux.yml`: ubuntu-latest, Node 24, runs the five spec files
above plus a shellcheck pass over `scripts/*.sh`. Runs on every PR touching `scripts/`,
`patches/`, or `.github/workflows/build-termux-*.yml`. Real-device coverage stays manual;
the ELF-header tests give arch correctness without hardware.

## Files to change

- new: `scripts/dsh_arch.py`, `scripts/lib/arch.sh`, `scripts/lib/elf.sh`,
  `scripts/dsh_arch.spec.ts`, `scripts/patch-termux.spec.ts`,
  `scripts/install-termux.spec.ts`, `scripts/e2e/install-devices.e2e.ts`,
  `.github/workflows/ci-termux.yml`
- `scripts/patch_termux.py` — resolver, dedupe, checks
- `scripts/install-termux.sh`, `scripts/install-prebuilt.sh`,
  `scripts/install-pty-prebuild.sh`, `scripts/install-sherpa-prebuild.sh` — resolver, verify
- `.github/workflows/build-termux-pty.yml`, `build-termux-sherpa.yml` — matrix + real gate
- `packages/experimental/speech-to-text-sensevoice/src/runtime.ts` — add `android-arm`,
  or fail with a clear message naming the arch
- `packages/session/session-persistence-jsonl/src/lease.ts` — comment only (logic is
  already platform-based; the doc says arm64 and should say android)

## Verification

1. `node scripts/patch_termux.py --check` passes, and each of the 21 patchers is covered.
2. Run the new specs: `pnpm vitest run scripts/dsh_arch.spec.ts scripts/patch-termux.spec.ts
   scripts/install-termux.spec.ts`.
3. On this device (arm32): `bash scripts/install-pty-prebuild.sh --file <arm32 fixture>`
   then `node -e "require('node-pty')"` — must resolve `prebuilds/android-arm`.
4. Simulate arm64 with `DSH_TARGET_ARCH=arm64` and assert the path becomes
   `prebuilds/android-arm64`.
5. Truncated-download test: confirm the installer aborts with a named error instead of
   falling into a local compile.
6. CI: the new workflow must fail if a fixture has the wrong `e_machine` for its
   directory — prove it by adding a deliberately wrong fixture in the PR and confirming red.

## Open question

Which arm64 device and error text did you see? If the arm64 failure is at download rather
than at pty load, the cause is Step 4 (network/verify), not the arch mapping. The fix covers
both, but knowing which lets us prioritize.
