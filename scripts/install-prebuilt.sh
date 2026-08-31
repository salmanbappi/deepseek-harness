#!/data/data/com.termux/files/usr/bin/bash
# install-prebuilt.sh — Download and apply the latest prebuilt Termux lib/ bundle
# Usage: bash install-prebuilt.sh [version]
set -euo pipefail

REPO="salmanbappi/deepseek-harness"
DSH_DIR="$HOME/deepseek-harness"

if [ -n "${1:-}" ]; then
  TAG="v$1"
else
  TAG=$(gh release list --repo "$REPO" --limit 1 --json tagName -q '.[0].tagName')
fi

echo "=== DeepSeek Harness Termux Prebuilt Installer ==="
echo "Release: $TAG"
echo "Target:  $DSH_DIR"
echo ""

# Download
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

echo "[1/4] Downloading prebuilt lib/ bundle..."
gh release download "$TAG" \
  --repo "$REPO" \
  --pattern "dsh-termux-prebuilt-*.tar.gz" \
  --dir "$TMPDIR_WORK"

ARCHIVE=$(ls "$TMPDIR_WORK"/dsh-termux-prebuilt-*.tar.gz | head -1)
echo "       Downloaded: $(basename "$ARCHIVE") ($(du -sh "$ARCHIVE" | cut -f1))"

# Extract compiled lib/ dirs into existing deepseek-harness tree
echo "[2/4] Extracting compiled lib/ dirs into $DSH_DIR ..."
tar -xzf "$ARCHIVE" -C "$DSH_DIR"

# Re-link node_modules (instant — no network, just symlinks)
echo "[3/4] Re-linking workspace node_modules (pnpm install --frozen-lockfile)..."
pnpm install --dir "$DSH_DIR" --frozen-lockfile --ignore-scripts 2>&1 | tail -5

# Refresh .dsh profile symlinks
echo "[4/4] Refreshing ~/.dsh/profiles node_modules symlinks..."
if [ -f "$HOME/.dsh/profiles/web/package.json" ]; then
  (cd "$HOME/.dsh/profiles" && pnpm install --frozen-lockfile --ignore-scripts 2>/dev/null) || true
fi

echo ""
echo "✓ Done! Run: dsh-web"
