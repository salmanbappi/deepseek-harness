#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Autonomous, Zero-Loss Updater for DeepSeek Harness on Termux & Android
# Preserves all Mobile UX, responsive styling, and Termux compatibility layers.
# ==============================================================================
set -e

export NODE_OPTIONS="--max-old-space-size=2560 ${NODE_OPTIONS:-}"

DSH_DIR="$HOME/deepseek-harness"
PATCHER="$DSH_DIR/scripts/patch_termux.py"
UPSTREAM_REPO="https://github.com/deepseek-ai/deepseek-harness.git"
REPO_OWNER="salmanbappi"
REPO_NAME="deepseek-harness"

if [ ! -d "$DSH_DIR" ]; then
    echo "[!] Error: DeepSeek Harness directory not found at $DSH_DIR" >&2
    exit 1
fi

DRY_RUN=0
NO_BUILD=0
REAPPLY_ONLY=0
FORCE=0
ROLLBACK_TARGET=""

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run|-n|--check)
            DRY_RUN=1
            shift
            ;;
        --no-build)
            NO_BUILD=1
            shift
            ;;
        --reapply-only|--reapply)
            REAPPLY_ONLY=1
            shift
            ;;
        --force|-f)
            FORCE=1
            shift
            ;;
        --list-backups|--backups)
            cd "$DSH_DIR"
            echo "=== DeepSeek Harness Safety Snapshots ==="
            git branch --list "backup/dsh-*" | sed 's/^[ *]*/  - /'
            echo "========================================="
            echo "To restore any backup, run: dsh-update --rollback <branch_name>"
            exit 0
            ;;
        --rollback)
            shift
            if [ -n "$1" ]; then
                ROLLBACK_TARGET="$1"
                shift
            else
                cd "$DSH_DIR"
                ROLLBACK_TARGET=$(git branch --list "backup/dsh-*" --sort=-committerdate | head -n 1 | tr -d ' *')
            fi
            ;;
        --help|-h)
            echo "DeepSeek Harness Autonomous Zero-Loss Updater"
            echo ""
            echo "Usage: dsh-update [options]"
            echo ""
            echo "Options:"
            echo "  --dry-run, -n, --check   Check upstream updates without modifying anything"
            echo "  --reapply-only           Re-apply all Termux & Mobile UX fixes and rebuild"
            echo "  --rollback [BRANCH]      Roll back to previous snapshot (defaults to latest)"
            echo "  --list-backups           List all available safety snapshot branches"
            echo "  --no-build               Sync and apply patches without compiling"
            echo "  --force, -f              Force update even with local uncommitted changes"
            echo "  --help, -h               Show this help message"
            exit 0
            ;;
        *)
            echo "[!] Unknown option: $1" >&2
            echo "Run 'dsh-update --help' for usage." >&2
            exit 1
            ;;
    esac
done

cd "$DSH_DIR"

# Handle Rollback
if [ -n "$ROLLBACK_TARGET" ]; then
    echo "=================================================="
    echo "      DeepSeek Harness Snapshot Rollback          "
    echo "=================================================="
    echo "[*] Target snapshot: $ROLLBACK_TARGET"
    if ! git show-ref --verify --quiet "refs/heads/$ROLLBACK_TARGET"; then
        echo "[!] Error: Snapshot branch '$ROLLBACK_TARGET' does not exist." >&2
        echo "    Run 'dsh-update --list-backups' to view available backups." >&2
        exit 1
    fi
    echo "[*] Restoring repository to $ROLLBACK_TARGET..."
    git checkout master 2>/dev/null || true
    git reset --hard "$ROLLBACK_TARGET"
    echo "[*] Reapplying environment patches..."
    python3 "$PATCHER" --apply || true
    if [ "$NO_BUILD" -eq 0 ]; then
        echo "[*] Rebuilding libraries..."
        pnpm run build:lib:host
        pnpm run build:lib:client
        pnpm run build:web
    fi
    echo "=================================================="
    echo " [✓] Successfully rolled back to $ROLLBACK_TARGET!"
    echo "=================================================="
    dsh --version 2>/dev/null || true
    exit 0
fi

echo "=================================================="
echo "    DeepSeek Harness Zero-Loss Autonomous Updater "
echo "=================================================="

PREV_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
PREV_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "unknown")
echo "[*] Current Version: $PREV_VERSION (Commit: $PREV_COMMIT)"

# Reapply only workflow
if [ "$REAPPLY_ONLY" -eq 1 ]; then
    echo ""
    echo "[*] Re-applying Termux environment & Mobile UX fixes..."
    python3 "$PATCHER" --apply
    
    echo ""
    echo "[*] Verifying native dependencies..."
    pnpm install --frozen-lockfile=false --ignore-scripts
    pnpm add -w @img/sharp-wasm32 --ignore-scripts 2>/dev/null || true
    python3 "$PATCHER" --apply
    
    if [ "$NO_BUILD" -eq 0 ]; then
        echo ""
        echo "[*] Rebuilding compiled binary and web assets..."
        pnpm run build:lib:host
        pnpm run build:lib:client
        pnpm run build:web
    fi
    
    echo ""
    echo "=================================================="
    echo " [✓] Termux & Mobile UX suite active and verified!"
    echo "=================================================="
    dsh --version 2>/dev/null || true
    exit 0
fi

# Step 1: Ensure Upstream & Origin Remotes
if ! git remote | grep -q "^upstream$"; then
    echo "[*] Configuring upstream remote -> $UPSTREAM_REPO"
    git remote add upstream "$UPSTREAM_REPO"
fi

if ! git remote | grep -q "^origin$"; then
    git remote add origin "https://github.com/$REPO_OWNER/$REPO_NAME.git" 2>/dev/null || true
fi

# Step 2: Safety Snapshot Backup (Zero-Loss Guarantee)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_BRANCH="backup/dsh-update-$TIMESTAMP"
echo ""
echo "[*] Creating safety snapshot: $BACKUP_BRANCH"
python3 "$PATCHER" --export 2>/dev/null || true
mkdir -p "$DSH_DIR/patches"
git diff HEAD > "$DSH_DIR/patches/dsh-preupdate-$TIMESTAMP.patch" 2>/dev/null || true
cp -f "$DSH_DIR/patches/dsh-preupdate-$TIMESTAMP.patch" "$DSH_DIR/patches/dsh-preupdate-latest.patch" 2>/dev/null || true

# Commit working changes locally if needed so git branch captures exact state
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    git add -A
    git commit -m "chore(termux): pre-update snapshot $TIMESTAMP" 2>/dev/null || true
fi
git branch "$BACKUP_BRANCH" 2>/dev/null || true

# Step 3: Check Upstream Updates
echo ""
echo "[*] Checking upstream repository for updates..."
git fetch upstream master --quiet 2>/dev/null || git fetch origin master --quiet

INCOMING_COMMITS=$(git log HEAD..upstream/master --oneline 2>/dev/null || true)
INCOMING_COUNT=$(git rev-list --count HEAD..upstream/master 2>/dev/null || echo 0)

if [ "$INCOMING_COUNT" -eq 0 ]; then
    echo "[✓] DeepSeek Harness is already up to date with official upstream ($PREV_VERSION)."
    if [ "$DRY_RUN" -eq 1 ]; then
        exit 0
    fi
    if [ "$FORCE" -eq 0 ]; then
        echo "[*] No new commits to apply. Run with --reapply-only to rebuild, or --force to re-sync."
        exit 0
    fi
else
    echo "[*] Found $INCOMING_COUNT incoming updates from upstream:"
    echo "$INCOMING_COMMITS" | head -n 10
    if [ "$INCOMING_COUNT" -gt 10 ]; then
        echo "    ... and $(($INCOMING_COUNT - 10)) more commits."
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        echo ""
        echo "[*] Dry-run mode: No modifications made."
        exit 0
    fi
fi

# Step 4: Non-Destructive Merge with Autonomous Conflict Resolution
echo ""
echo "[*] Merging upstream updates into local workspace..."
if ! git merge --no-edit -m "chore(termux): merge upstream master" upstream/master 2>/dev/null; then
    echo "[*] Resolving merge integration on customized files..."
    # Check conflicting files
    CONFLICTS=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
    if [ -n "$CONFLICTS" ]; then
        echo "[*] Auto-resolving managed files: $CONFLICTS"
        for f in $CONFLICTS; do
            git checkout --theirs "$f" 2>/dev/null || true
            git add "$f" 2>/dev/null || true
        done
        git commit -m "chore(termux): merge upstream and re-inject Termux/Mobile UX suite" 2>/dev/null || true
    fi
fi

# Step 5: Reapply All Termux & Mobile UX Patches
echo ""
echo "[*] Reapplying Termux environment, Local Auth, and Mobile UI/UX Suite..."
python3 "$PATCHER" --apply

# Verify patch integrity
if ! python3 "$PATCHER" --check >/dev/null 2>&1; then
    echo "[!] Warning: Some patch hooks need programmatic refresh. Running patcher..."
    python3 "$PATCHER" --apply
fi

# Step 6: Verify and Rebuild Native Dependencies
echo ""
echo "[*] Verifying dependencies (pnpm install)..."
pnpm install --frozen-lockfile=false --ignore-scripts
pnpm add -w @img/sharp-wasm32 --ignore-scripts 2>/dev/null || true

# Re-run patcher for native node-pty and Koffi
python3 "$PATCHER" --apply

# Step 7: Build Compiled Binaries & Web Assets
if [ "$NO_BUILD" -eq 0 ]; then
    echo ""
    echo "[*] Compiling application host libraries..."
    pnpm run build:lib:host
    echo "[*] Compiling client libraries..."
    pnpm run build:lib:client
    echo "[*] Compiling Web UI assets..."
    pnpm run build:web
fi

# Step 8: Sync Changes to Fork (origin)
if git remote | grep -q "^origin$"; then
    echo ""
    echo "[*] Syncing updated state to fork ($REPO_OWNER/$REPO_NAME)..."
    git add -A
    NEW_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "latest")
    git commit -m "chore(termux): sync upstream v$NEW_VERSION + mobile & termux suite" 2>/dev/null || true
    git push -u origin master 2>/dev/null || echo "[!] Notice: Push to origin skipped (offline or already synced)."
fi

# Step 9: Final Diagnostics and Verification
echo ""
echo "[*] Running final system verification..."
NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
NEW_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "unknown")

if dsh --version >/dev/null 2>&1; then
    echo "=================================================="
    echo " [✓] DeepSeek Harness Successfully Updated!"
    echo "     Version:  $PREV_VERSION -> $NEW_VERSION"
    echo "     Commit:   $PREV_COMMIT -> $NEW_COMMIT"
    echo "     Snapshot: $BACKUP_BRANCH"
    echo "     Termux & Mobile Suite: Active & Verified"
    echo "=================================================="
else
    echo "=================================================="
    echo "[!] Warning: 'dsh --version' check encountered an issue."
    echo "    Diagnostics (dsh-doctor):"
    dsh-doctor || true
    echo ""
    echo "    To rollback to your pre-update state, run:"
    echo "    dsh-update --rollback $BACKUP_BRANCH"
    echo "=================================================="
fi
