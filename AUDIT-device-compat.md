# dsh-mobile — device compatibility audit

Audit of `~/dsh-mobile` (`SehonYT/dsh-termux`, v0.2.2-rc.1).
Read-only findings, before any code change.

## Context

Goal: make the installer work on every Android device, not just aarch64 Termux, and optimize
for mobile. Reported symptom: **on arm64 the install succeeds but `dsh` throws a pnpm error at
startup**; on other devices it fails outright.

## PRIMARY ROOT CAUSE (arm64 startup failure): the pinned pnpm has no Android binary

`package.json` pins `packageManager: pnpm@11.28.5`. That release publishes platform binaries
for exactly these targets:

```
@pnpm/linux-arm64, @pnpm/linux-x64, @pnpm/linuxstatic-x64,
@pnpm/macos-arm64, @pnpm/win-arm64, @pnpm/win-x64
```

**No `android-*` variant at all.** So on every Android device, corepack/pnpm cannot execute
the pinned version. Observed on this device:

```
$ corepack pnpm --version
Downloading the pnpm 12.18.0 binary for android-arm...
Could not download the pnpm 12.18.0 binary:
  Sorry! pnpm does not provide a pre-built binary for android-arm.
```

Version support across releases (from the npm registry):

| pnpm | Android targets shipped |
|---|---|
| 9.15.9 | none |
| 11.28.5 (pinned here) | none |
| 12.18.0 | `android-arm64`, `android-x64` — **no `android-arm`** |

Consequences:
- **arm64 phone**: the `pnpm@11.28.5` pin cannot resolve → startup error.
- **arm32 phone** (this one): no pnpm release has an android-arm binary, including the newest.
  The only working pnpm is the Termux-packaged native build
  (`/usr/bin/pnpm`, v12.19.0, `Architecture: arm`, an NDK-built ARM32 ELF).

### What works today, and why it "sometimes" works

`/usr/bin/pnpm` is a **32-bit ARM ELF**, not a corepack shim, so it bypasses corepack. Running
`pnpm --version` in the repo then emits a warning (not an error) and proceeds:

```
[WARN] Cannot use the pnpm version this project pins:
  ERR_PNPM_PNPM_ENGINE_NO_NATIVE_BINARY ... it ships no native binary for android-arm.
  Set `pmOnFail` to `ignore` to skip the version switch.
12.10.1
```

`pnpm --pm-on-fail=ignore` suppresses it and exits clean; setting `pm-on-fail` in `.npmrc`
does **not**, because the version check runs before config is read. The env var
`npm_config_pm_on_fail` also does not suppress it.

So the fix must not rely on `.npmrc` or the environment. It has to either drop the
`packageManager` pin on Android, or stop the pinned resolution from being attempted.

## SECONDARY ROOT CAUSE (install/run failure on non-arm64): native binary arch is hardcoded

## Root cause: architecture is hardcoded to aarch64 in some places and wrong in others

The system has **no single source of truth for architecture**. Five places each assume
something different.

### 1. The prebuilt release tarball ships ZERO native binaries

`dsh-termux-prebuilt-v0.2.2-rc.1.tar.gz` (35 MB, 6121 entries) contains 6015 `lib/` files and
**0 `.node` files**. So after install, `node-pty` has no binary at all. Nothing can load it
until `patch_termux.py` copies one in from `~/.dsh/native/`.

Verified: `tar -tzf … | grep -c '\.node$'` → 0.

### 2. CI builds arm64 only

`.github/workflows/build-termux-pty.yml`:
- `npx node-gyp@11 rebuild --arch=arm64 --target=…` (line 76)
- `CC=$TC/aarch64-linux-android24-clang` (line 67)
- Runs inside `termux/termux-docker:aarch64` (line 120)
- `build-termux-sherpa.yml` is likewise `android-aarch64-termux`
- `cua-driver-*-android-arm64` is the only Android package in `minimumReleaseAgeExclude`

There is **no arm32 / x86_64 build job anywhere**.

### 3. The "Verify ELF targets bionic/aarch64" step does not verify aarch64

`build-termux-pty.yml:79-92` runs `readelf -h … | grep -E 'Class|Machine|Type'` — which only
**prints**. The single assertion in that step is:

```sh
if readelf -W --dyn-syms build/Release/pty.node | grep -q 'GLIBC_'; then exit 1; fi
```

It rejects glibc symbol imports and nothing else. A 32-bit ARM binary passes this gate
silently. That is how a mislabeled binary can be published as `android-arm64`.

### 4. The cached binary on this device is 32-bit, in a folder named android-arm64

`~/.dsh/native/android-arm64/pty.node`:
```
ELF 32-bit LSB shared object, ARM, EABI5, dynamically linked, for Android 24,
built by NDK r30, not stripped
e_machine = 40  (ARM/32-bit, not 183/AARCH64)
```
It loads on this device because this device's Node is `process.arch === 'arm'`
(`uname -m` = `armv8l`, 32-bit userland on 64-bit silicon).

On a genuine aarch64 Termux, `process.arch === 'arm64'` and this binary cannot `dlopen`.
That is a concrete "arm64 device fails" mechanism.

### 5. `install-pty-prebuild.sh` hard-rejects every non-aarch64 device

`scripts/install-pty-prebuild.sh:82-88`:
```sh
case "$DESC" in
    *"ELF 64-bit"*"ARM aarch64"*) ok ;;
    *) err "not an aarch64 shared object: $DESC"; exit 1 ;;
esac
```
On this 32-bit device this exits 1. The fallback path for a user whose pty is missing is
therefore unusable on arm32, even though a working arm32 binary exists in the cache.

### 6. `android-arm64` is a literal string in ~10 places, with no arch mapping

- `scripts/patch_termux.py:28` `NATIVE_CACHE_DIR = …/native/android-arm64`
- `scripts/patch_termux.py:733,741,745,753` prebuild dir + messages
- `scripts/patch_termux.py:760+` same for `fs-ext`
- `scripts/install-prebuilt.sh:61-66` `PTY_CACHE` and `prebuilds/android-arm64`
- `scripts/install-pty-prebuild.sh:20,84,102,106` cache dir, ELF gate, install target
- `scripts/patch_termux.py:14` speech `android-arm64`

The folder name must match what node-pty's `loadNativeModule` searches. Nothing maps
`process.arch` → folder name, so arm32 and x64 devices get the arm64 name (or fail).

## Secondary install defects

### 7. Partial/corrupt download is treated as success
`install-termux.sh:295` gates on `[ -f "$DEST_TAR" ] && [ -s "$DEST_TAR" ]` — non-empty only.
The Python downloader opens with `'wb'` and writes incrementally, so a mid-stream failure
leaves a truncated file that passes `-s`, then `tar -xzf … || true` fails silently and the
installer falls through to local compile. There is also **no checksum or size verification**
against `content-length`, and no resumable/retry logic.

### 8. `apply_all()` calls 10 patchers twice
`scripts/patch_termux.py` `apply_all()` invokes `patch_fs_ext`, `patch_ripgrep`,
`patch_settings_mobile`, `patch_llm_pi_ai_gateway`, `patch_user_questions_mobile`,
`patch_trajectory_mobile`, `patch_conversation_mobile`, `patch_speech_to_text`,
`patch_bundle_layer_cache`, `patch_fs_batch_edits` a second time (lines ~1877-1896).
Only safe because each patcher is marker-idempotent. Doubles work on a phone.

### 9. 21 patchers, only 15 `--check` invariants
Unverified patchers: `patch_koffi`, `patch_node_pty`, `patch_fs_ext`, `patch_ripgrep`,
`patch_bundle_layer_cache`, `patch_fs_batch_edits`. Of these, `patch_node_pty`/`patch_fs_ext`
are exactly the arch-dependent ones. A missing pty binary passes `--check` today.

### 10. `--check` is substring presence, not behavior
Every check is `marker in file_contents`. It proves a string exists, not that the code works.
`all_ok` is a hand-written 15-term boolean chain — adding a check to the file does not add it
to the chain, and forgetting that silently weakens the gate.

## What this means for the plan

The arch fix is the spine: one helper that resolves `process.arch`/`uname -m` to
(node-pty loader dir name, native cache dir, CI artifact name), used by every script above,
plus CI building and verifying each supported arch with a real arch assertion.

Device matrix to support:
- `arm64` / aarch64 (most modern phones)
- `arm` / armv7l / armv8l (32-bit userland on 64-bit silicon — this device)
- `x64` (emulators, ChromeOS, some tablets)

## Open questions

- Which devices are reported failing, exactly? Need `uname -m`, `getconf LONG_BIT`,
  `node -p process.arch`, and the installer's error text from a failing arm64 phone.
- Is the arm64 failure at download (network) or at pty load (arch)? The path differs.
