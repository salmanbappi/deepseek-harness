# DeepSeek Harness

DeepSeek Harness (`dsh`) is an open-source autonomous agent execution environment developed by DeepSeek AI and maintained for Android (Termux) and Desktop platforms.

Powered by the Cordis plugin microkernel, DeepSeek Harness provides a modular runtime for model tool calling, persistent sandboxed execution, terminal sessions, and interactive interfaces.

---

## Supported Platforms

- **Android (Termux):** Optimized for ARM64 mobile environments with hardware-accelerated speech-to-text, terminal emulation, and zero-compile cloud prebuilts.
- **Desktop (Windows and macOS):** Packaged standalone application running an authenticated local host and desktop workspace.

---

## Installation

### Android (Termux)

#### Automated One-Line Installer

The automated installer configures minimal dependencies, downloads pre-compiled release bundles, links workspace binaries, and exposes global executables:

```sh
curl -sL https://raw.githubusercontent.com/salmanbappi/deepseek-harness/master/scripts/install-termux.sh | bash
```

#### Manual Installation from Prebuilt Bundle

For manual deployment without local compilation load:

```sh
git clone --depth=1 https://github.com/salmanbappi/deepseek-harness.git ~/deepseek-harness
cd ~/deepseek-harness
bash scripts/install-prebuilt.sh
```

---

### Desktop (Windows and macOS)

Standalone pre-packaged distributions with bundled runtimes are distributed via GitHub Releases:

1. Navigate to the repository releases page: `https://github.com/salmanbappi/deepseek-harness/releases`
2. Download the package for your architecture:
   - **Windows (x64):** `deepseek-harness-*-win-x64-unsigned.exe` (Installer) or `DeepSeek.Harness.exe` (Portable)
   - **macOS (Apple Silicon):** `dsh-desktop-macos-arm64-*.tar.gz`
3. Launch or unpack the package. No local compilation toolchain or Node.js runtime configuration is required.

---

### Run from Source

To build and run from source in a development environment:

```sh
git clone --depth=1 https://github.com/salmanbappi/deepseek-harness.git
cd deepseek-harness
pnpm install
pnpm run build
pnpm dsh web
```

---

## Execution and Diagnostics

### Start Web Interface

```sh
dsh web
```

Launches the local HTTP service and user interface at `http://127.0.0.1:3080`. Pass `--no-open` to inhibit automatic browser launching.

### System Diagnostics

Validate platform patches, native addons, and runtime health:

```sh
dsh-doctor
```

### Upstream Synchronization

Upgrade to the latest releases while maintaining mobile and platform optimizations:

```sh
dsh-update
```

---

## License

Distributed under the MIT License. See `LICENSE` for details.
