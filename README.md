# DeepSeek Harness (Termux & Mobile Edition)

[![Termux Compatibility](https://img.shields.io/badge/Termux-Android%20arm64-green.svg)](https://github.com/salmanbappi/deepseek-harness)
[![Mobile UX](https://img.shields.io/badge/UX-Mobile%20Optimized-blue.svg)](https://github.com/salmanbappi/deepseek-harness)
[![Build Status](https://github.com/salmanbappi/deepseek-harness/actions/workflows/build-termux.yml/badge.svg)](https://github.com/salmanbappi/deepseek-harness/actions/workflows/build-termux.yml)
[![Release](https://img.shields.io/github/v/release/salmanbappi/deepseek-harness?include_prereleases)](https://github.com/salmanbappi/deepseek-harness/releases)

English | [中文](README.zh.md)

**DeepSeek Harness (`dsh`)** is an open-source agent harness developed by [DeepSeek AI](https://deepseek.com), powered by [Cordis](https://github.com/cordiverse/cordis).

This repository is an optimized distribution specifically adapted for **Android Termux** and **Mobile Web Browsers**, featuring zero-loss automated upstream upgrades, Android filesystem workarounds, and responsive mobile UI enhancements.

---

## 📱 Mobile & Termux Enhancements

* **Android Filesystem Compatibility**:
  - Implements atomic `rename` fallback when hardlinks fail with `EACCES`, `EPERM`, or `EXDEV` on Android internal storage (`/data/data/com.termux/files/home`). File attachments and chat session persistence work seamlessly.
* **Responsive Mobile Web UI**:
  - **Slide-out Navigation Drawer**: Clean mobile sidebar toggle with backdrop touch dismiss.
  - **Single-Line AI Message Footer**: Compact inline action icons and response metrics (`16:08 · Ran for 5s · TTFT · tok/s`) styled to fit narrow mobile viewports without wrapping or breaking.
  - **Touch & Dropdown Support**: Fixed pointer events for model selection, settings modals, and touch dropdowns.
* **Native ARM64 Terminal & Image Engine**:
  - Pre-configured WASM image rasterizer (`@img/sharp-wasm32`) and native `node-pty` terminal bindings built for Android ARM64.
* **Self-Healing Updater (`dsh-update`)**:
  - Autonomous update pipeline that pulls new upstream features while automatically safeguarding, re-applying, and verifying your Termux mobile patches.
* **Health Inspector (`dsh-doctor`)**:
  - Comprehensive diagnostic tool auditing Node.js, Python, Android filesystem patches, local browser auth bypass, and native modules.

---

## 🚀 Quickstart on Android Termux

### ⚡ 1-Line Automated Install (Fastest)

Open Termux and run this single command to automatically install dependencies, clone the repository, apply all mobile & Termux patches, build assets, and configure global `dsh` commands:

```sh
curl -sSL https://raw.githubusercontent.com/salmanbappi/deepseek-harness/master/scripts/install-termux.sh | bash
```

Once installed, start the web interface anywhere with:
```sh
dsh web
```

---

### Option 2: Manual Installation from Source


1. **Install Prerequisites in Termux**:
   ```sh
   pkg update && pkg install nodejs-lts python git pnpm clang make
   ```

2. **Clone and Install**:
   ```sh
   git clone https://github.com/salmanbappi/deepseek-harness.git
   cd deepseek-harness
   pnpm install
   pnpm run build
   ```

3. **Launch the Web Interface**:
   ```sh
   pnpm dsh web
   ```
   Open `http://127.0.0.1:3080` in Chrome, Firefox, or your preferred mobile browser.

---

### Option 2: Pre-compiled GitHub Releases

Download the pre-built tarball bundle directly from [Releases](https://github.com/salmanbappi/deepseek-harness/releases/latest):

```sh
# Download and extract the latest prebuilt release
curl -LO $(curl -s https://api.github.com/repos/salmanbappi/deepseek-harness/releases/latest | grep "browser_download_url.*dsh-termux-.*\.tar\.gz" | cut -d : -f 2,3 | tr -d \")
tar -xzf dsh-termux-*.tar.gz
cd deepseek-harness
node apps/cli/lib/bin.js web
```

---

## 🔄 Keeping Up-to-Date (`dsh-update`)

To update your installation to the latest upstream release without losing mobile optimizations:

```sh
dsh-update
```

What `dsh-update` does automatically:
1. Creates a safety backup branch (`backup/dsh-update-<timestamp>`).
2. Pulls and merges the newest official commits from `deepseek-ai/deepseek-harness`.
3. Re-injects all Termux & Mobile UX patches cleanly.
4. Verifies dependencies and rebuilds libraries.
5. Runs a health check to confirm everything is operational.

---

## 🩺 Diagnostics (`dsh-doctor`)

Run the health check utility at any time to verify system integrity:

```sh
dsh-doctor
```

Output checklist:
- `[*] Checking Node.js, pnpm, Python3`
- `[*] Android File Attachment Fallback:  [PASS]`
- `[*] Android Session Persistence:       [PASS]`
- `[*] Local Mobile Auth Bypass:          [PASS]`
- `[*] Responsive Mobile Drawer & UI:     [PASS]`
- `[*] Touch & Dropdown Handling:         [PASS]`
- `[*] Runtime Engine Flags & Wasm:       [PASS]`
- `[*] Native Modules & Terminal (pty):   [PASS]`

---

## 💻 Standard Run (Desktop / Server)

### Run from `npm`

```sh
npx @deepseek-ai/dsh web
```

### Run from source

```sh
git clone https://github.com/salmanbappi/deepseek-harness.git
cd deepseek-harness
pnpm install
pnpm run build
pnpm dsh web
```

---

## 🤝 Community and Support

- Official Documentation: [deepseek-harness.github.io](https://deepseek-harness.github.io/deepseek-harness/)
- Termux Fork Issues & Feedback: [salmanbappi/deepseek-harness/issues](https://github.com/salmanbappi/deepseek-harness/issues)
- DeepSeek Discussions: [deepseek-ai/deepseek-harness/discussions](https://github.com/deepseek-ai/deepseek-harness/discussions)
- Discord Community: <a href="https://discord.gg/Ycq5dCaS4">DeepSeek Harness Discord</a>

---

## 📄 License

[MIT](LICENSE) · Disclosures in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

