#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
#  DeepSeek Harness — Automated 1-Line Termux & Mobile Installer
#  Repository: https://github.com/salmanbappi/deepseek-harness
# ==============================================================================
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ======================================================="
echo "       DeepSeek Harness (Termux & Mobile Edition)        "
echo "               Automated Setup Installer                 "
echo "  ======================================================="
echo -e "${NC}"

# 1. System packages check & installation
echo -e "${BLUE}[1/5] Checking and installing Termux system packages...${NC}"
pkg update -y || true
PACKAGES="nodejs-lts python git pnpm clang make binutils"
for pkg in $PACKAGES; do
    if ! command -v "$pkg" &>/dev/null && ! dpkg -s "$pkg" &>/dev/null; then
        echo -e "${YELLOW}  -> Installing $pkg...${NC}"
        pkg install -y "$pkg" || true
    fi
done

# 2. Repository setup
DSH_DIR="$HOME/deepseek-harness"
echo -e "${BLUE}[2/5] Setting up DeepSeek Harness repository at $DSH_DIR...${NC}"
if [ -d "$DSH_DIR/.git" ]; then
    echo "  -> Existing repository found. Fetching latest updates..."
    cd "$DSH_DIR"
    git fetch origin master || true
    git checkout master || true
    git pull origin master || true
else
    echo "  -> Cloning salmanbappi/deepseek-harness..."
    git clone https://github.com/salmanbappi/deepseek-harness.git "$DSH_DIR"
    cd "$DSH_DIR"
fi

# 3. CLI Helper Commands Installation (~/bin)
echo -e "${BLUE}[3/5] Installing global commands (dsh, dsh-update, dsh-doctor)...${NC}"
BIN_DIR="$HOME/bin"
mkdir -p "$BIN_DIR"

# Install dsh launcher
cat <<'LAUNCHER_EOF' > "$BIN_DIR/dsh"
#!/data/data/com.termux/files/usr/bin/bash
set -e
DSH_DIR="$HOME/deepseek-harness"
if [ ! -d "$DSH_DIR" ]; then
    echo "[!] Error: DeepSeek Harness directory not found at $DSH_DIR" >&2
    exit 1
fi
if [ -f "$DSH_DIR/apps/cli/lib/bin.js" ]; then
    exec node --expose-internals "$DSH_DIR/apps/cli/lib/bin.js" "$@"
else
    exec node --expose-internals --import "$DSH_DIR/node_modules/tsx/dist/esm/index.mjs" "$DSH_DIR/apps/cli/src/bin.ts" "$@"
fi
LAUNCHER_EOF
chmod +x "$BIN_DIR/dsh"

# Install dsh-update
cp -f "$DSH_DIR/scripts/dsh-update.sh" "$BIN_DIR/dsh-update" 2>/dev/null || true
chmod +x "$BIN_DIR/dsh-update" 2>/dev/null || true

# Install dsh-doctor
cat <<'DOCTOR_EOF' > "$BIN_DIR/dsh-doctor"
#!/data/data/com.termux/files/usr/bin/bash
set -e
DSH_DIR="$HOME/deepseek-harness"
echo "=========================================="
echo "      DeepSeek Harness Termux Doctor      "
echo "=========================================="
echo "[*] Checking Node.js:  $(node -v 2>/dev/null || echo 'FAIL')"
echo "[*] Checking pnpm:     $(pnpm -v 2>/dev/null || echo 'FAIL')"
echo "[*] Checking Python3:  $(python3 --version 2>/dev/null || echo 'FAIL')"
echo "[*] Harness Directory: Found at $DSH_DIR"
if [ -d "$DSH_DIR" ]; then
    cd "$DSH_DIR"
    python3 scripts/patch_termux.py --check || true
fi
echo "=========================================="
DOCTOR_EOF
chmod +x "$BIN_DIR/dsh-doctor"

# Install dsh-patch
cat <<'PATCH_EOF' > "$BIN_DIR/dsh-patch"
#!/data/data/com.termux/files/usr/bin/bash
set -e
DSH_DIR="$HOME/deepseek-harness"
if [ ! -d "$DSH_DIR" ]; then
    echo "[!] Error: Harness directory not found at $DSH_DIR" >&2
    exit 1
fi
cd "$DSH_DIR"
python3 "$DSH_DIR/scripts/patch_termux.py" "$@"
PATCH_EOF
chmod +x "$BIN_DIR/dsh-patch"

# Ensure PATH has ~/bin in shell profiles
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$rc" ]; then
        if ! grep -q 'HOME/bin' "$rc"; then
            echo 'export PATH="$HOME/bin:$PATH"' >> "$rc"
        fi
    else
        echo 'export PATH="$HOME/bin:$PATH"' > "$rc"
    fi
done
export PATH="$HOME/bin:$PATH"

# 4. Dependency installation & Termux patch application
echo -e "${BLUE}[4/5] Applying Termux & Mobile UX patches and installing dependencies...${NC}"
cd "$DSH_DIR"
python3 scripts/patch_termux.py --apply || true
pnpm install --frozen-lockfile=false --ignore-scripts
pnpm add -w @img/sharp-wasm32 --ignore-scripts 2>/dev/null || true
python3 scripts/patch_termux.py --apply || true

# 5. Build libraries and web assets
echo -e "${BLUE}[5/5] Building TypeScript libraries and mobile web interface...${NC}"
pnpm run build:lib:host
pnpm run build:lib:client
pnpm run build:web

echo -e "\n${GREEN}=======================================================${NC}"
echo -e "${GREEN}   DeepSeek Harness successfully installed on Termux!  ${NC}"
echo -e "${GREEN}=======================================================${NC}"
echo -e "
${CYAN}Commands Available Everywhere:${NC}
  ${YELLOW}dsh web${NC}        -> Start the Web UI at http://127.0.0.1:3080
  ${YELLOW}dsh-update${NC}     -> Upgrade to latest upstream without losing fixes
  ${YELLOW}dsh-doctor${NC}     -> Verify environment & patch integrity

${CYAN}To Start Right Now:${NC}
  ${YELLOW}dsh web${NC}
"
