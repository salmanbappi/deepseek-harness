# DeepSeek Harness

DeepSeek Harness (`dsh`) is an open-source autonomous agent execution environment developed by DeepSeek AI and optimized for Android (Termux) ARM64 architectures.

Powered by the Cordis plugin microkernel, DeepSeek Harness provides a modular runtime for model tool calling, persistent sandboxed execution, terminal sessions, speech-to-text, and local web interfaces.

---

## Installation

### Automated One-Line Installer

The automated installer configures system packages, downloads pre-compiled zero-compile release bundles, links workspace binaries, and exposes global executables:

```sh
curl -sL https://raw.githubusercontent.com/salmanbappi/deepseek-harness/master/scripts/install-termux.sh | bash
```

### Manual Installation from Prebuilt Bundle

For manual deployment without local compilation:

```sh
git clone --depth=1 https://github.com/salmanbappi/deepseek-harness.git ~/deepseek-harness
cd ~/deepseek-harness
bash scripts/install-prebuilt.sh
```

### Run from Source

To build and run from source in a Termux development environment:

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

Upgrade to the latest releases while maintaining mobile optimizations:

```sh
dsh-update
```

---

## License

Distributed under the MIT License. See `LICENSE` for details.
