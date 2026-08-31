#!/data/data/com.termux/files/usr/bin/bash
# install-prebuilt.sh — Download and apply the latest prebuilt Termux bundle
# Usage: bash install-prebuilt.sh [version]
set -euo pipefail

REPO="salmanbappi/deepseek-harness"
DSH_DIR="$HOME/deepseek-harness"

if [ -n "${1:-}" ]; then
  TAG="v$1"
else
  TAG=$(gh release view --repo "$REPO" --json tagName -q .tagName 2>/dev/null || echo "latest")
  [ "$TAG" = "latest" ] && TAG=$(gh release list --repo "$REPO" --limit 1 --json tagName -q '.[0].tagName')
fi

echo "=== DeepSeek Harness Termux Prebuilt Installer ==="
echo "Release: $TAG"
echo "Target:  $DSH_DIR"
echo ""

# Download
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

echo "[1/3] Downloading release assets..."
gh release download "$TAG" \
  --repo "$REPO" \
  --pattern "dsh-termux-prebuilt-*.tar.gz" \
  --dir "$TMPDIR_WORK"

ARCHIVE=$(ls "$TMPDIR_WORK"/*.tar.gz | head -1)
echo "       Downloaded: $(basename "$ARCHIVE") ($(du -sh "$ARCHIVE" | cut -f1))"

# Extract
echo "[2/3] Extracting into $DSH_DIR ..."
mkdir -p "$DSH_DIR"
tar --dereference -xzf "$ARCHIVE" -C "$DSH_DIR"

# Restore profile node_modules symlinks (lightweight — no compilation)
echo "[3/3] Refreshing ~/.dsh profile symlinks..."
if [ -f "$HOME/.dsh/profiles/web/package.json" ]; then
  (cd "$HOME/.dsh/profiles" && pnpm install --ignore-scripts 2>/dev/null) || true
fi

echo ""
echo "✓ Done! Run: dsh-web"
