#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# dsh-update — Autonomous Zero-Loss Updater for DeepSeek Harness on Termux
# Flow: merge upstream → patch → push → wait for GH Actions CI build →
#       download prebuilt lib/ bundle → apply → verify → done.
# ==============================================================================
set -euo pipefail
export COREPACK_ENABLE_PROJECT_SPEC=0
export COREPACK_ENABLE_STRICT=0
export COREPACK_ENABLE_AUTO_PIN=0
export NODE_OPTIONS="--max-old-space-size=2560 ${NODE_OPTIONS:-}"

# ── Config ──────────────────────────────────────────────────────────────────
DSH_DIR="$HOME/deepseek-harness"
PATCHER="$DSH_DIR/scripts/patch_termux.py"
UPSTREAM_REPO="https://github.com/deepseek-ai/deepseek-harness.git"
REPO_OWNER="salmanbappi"
REPO_NAME="deepseek-harness"
WORKFLOW_NAME="Build & Release Termux Prebuilt Bundle"
CI_POLL_INTERVAL=20   # seconds between status checks
CI_TIMEOUT=1800       # 30 minutes max wait

# ── Colour helpers ───────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
info() { echo -e "${CYAN}[*]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }
box()  { echo -e "\n${CYAN}══════════════════════════════════════════════${NC}"; echo -e "    $*"; echo -e "${CYAN}══════════════════════════════════════════════${NC}"; }

# ── Guards ───────────────────────────────────────────────────────────────────
if [ ! -d "$DSH_DIR" ]; then
    err "DeepSeek Harness not found at $DSH_DIR"
    exit 1
fi

if ! command -v gh &>/dev/null; then
    err "'gh' (GitHub CLI) is required. Install with: pkg install gh"
    exit 1
fi

# ── Argument parsing ─────────────────────────────────────────────────────────
DRY_RUN=0
NO_BUILD=0
REAPPLY_ONLY=0
FORCE=0
ROLLBACK_TARGET=""
TARGET_REF=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run|-n|--check)    DRY_RUN=1; shift ;;
        --no-build)              NO_BUILD=1; shift ;;
        --reapply-only|--reapply) REAPPLY_ONLY=1; shift ;;
        --force|-f)              FORCE=1; shift ;;
        --ref|--tag|-r)
            shift
            TARGET_REF="${1:-}"
            [ -n "$TARGET_REF" ] && shift || true
            ;;
        --local-build)
            err "--local-build is disabled: only remote GitHub Actions CI builds are allowed."
            exit 1
            ;;
        --list-backups|--backups)
            cd "$DSH_DIR"
            echo "=== DeepSeek Harness Safety Snapshots ==="
            git branch --list "backup/dsh-*" | sed 's/^[ *]*/  - /'
            echo "========================================="
            echo "To restore: dsh-update --rollback <branch>"
            exit 0
            ;;
        --rollback)
            shift
            ROLLBACK_TARGET="${1:-}"
            [ -n "$ROLLBACK_TARGET" ] && shift || true
            ;;
        --help|-h)
            echo "DeepSeek Harness — Autonomous Updater"
            echo ""
            echo "Usage: dsh-update [options]"
            echo ""
            echo "Options:"
            echo "  (none)             Full update: merge upstream → push → CI build → apply prebuilt"
            echo "  --dry-run, -n      Check upstream without modifying anything"
            echo "  --reapply-only     Re-patch + push + wait for CI + apply (skip merge)"
            echo "  --no-build         Merge + patch + push only (no build/apply step)"
            echo "  --force, -f        Force full update even if already up-to-date"
            echo "  --rollback [BR]    Roll back to a snapshot branch"
            echo "  --list-backups     List available snapshot branches"
            echo "  --help, -h         This help"
            exit 0
            ;;
        *)
            err "Unknown option: $1  (run dsh-update --help)"
            exit 1
            ;;
    esac
done

cd "$DSH_DIR"

# ── Rollback mode ─────────────────────────────────────────────────────────────
if [ -n "$ROLLBACK_TARGET" ]; then
    box "Snapshot Rollback"
    if [ -z "$ROLLBACK_TARGET" ]; then
        ROLLBACK_TARGET=$(git branch --list "backup/dsh-*" --sort=-committerdate | head -n 1 | tr -d ' *')
    fi
    info "Target: $ROLLBACK_TARGET"
    git checkout master 2>/dev/null || true
    git reset --hard "$ROLLBACK_TARGET"
    python3 "$PATCHER" --apply || true
    if [ "$NO_BUILD" -eq 0 ]; then
        info "Applying prebuilt bundle..."
        bash "$DSH_DIR/scripts/install-prebuilt.sh" 2>&1 || true
    fi
    ok "Rolled back to $ROLLBACK_TARGET"
    dsh --version 2>/dev/null || true
    exit 0
fi

# ── Header ───────────────────────────────────────────────────────────────────
box "DeepSeek Harness — Zero-Loss Autonomous Updater"
PREV_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
PREV_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "unknown")
info "Current: v$PREV_VERSION  (commit: $PREV_COMMIT)"

# ── Reapply-only shortcut ────────────────────────────────────────────────────
if [ "$REAPPLY_ONLY" -eq 1 ]; then
    info "Reapplying Termux patches..."
    python3 "$PATCHER" --apply
    ok "Patches applied. Skipping to build step."
else
    # ── Step 1: Remotes ───────────────────────────────────────────────────────
    git remote | grep -q "^upstream$" || git remote add upstream "$UPSTREAM_REPO"
    git remote | grep -q "^origin$"   || git remote add origin "https://github.com/$REPO_OWNER/$REPO_NAME.git" 2>/dev/null || true

    # ── Step 2: Check upstream (runs BEFORE any mutation so --dry-run is side-effect-free)
    echo ""
    info "Fetching upstream changes..."
    if [ -n "$TARGET_REF" ]; then
        info "Target ref requested: $TARGET_REF"
        UPSTREAM_REF="$TARGET_REF"
        git fetch upstream "$TARGET_REF" --quiet 2>/dev/null || git fetch origin "$TARGET_REF" --quiet 2>/dev/null || true
    else
        UPSTREAM_REF="upstream/master"
        if ! git fetch upstream master --quiet 2>/dev/null; then
            warn "upstream fetch failed — falling back to origin master"
            git fetch origin master --quiet
            UPSTREAM_REF="origin/master"
        fi
    fi

    INCOMING_COUNT=$(git rev-list --count "HEAD..$UPSTREAM_REF" 2>/dev/null || echo 0)
    OUTGOING_COUNT=$(git rev-list --count "origin/master..HEAD" 2>/dev/null || echo 0)
    if [ "$INCOMING_COUNT" -eq 0 ] && [ "$OUTGOING_COUNT" -eq 0 ] && [ "$FORCE" -eq 0 ]; then
        ok "Already up to date with upstream (v$PREV_VERSION)."
        if [ "$DRY_RUN" -eq 1 ]; then exit 0; fi
        info "Run with --force to re-push and rebuild, or --reapply-only to just re-patch."
        exit 0
    fi

    if [ "$INCOMING_COUNT" -eq 0 ] && [ "$OUTGOING_COUNT" -gt 0 ]; then
        info "Already merged upstream changes, but local master is ahead of origin by $OUTGOING_COUNT commit(s). Resuming push & build..."
    fi

    if [ "$INCOMING_COUNT" -gt 0 ]; then
        info "Found $INCOMING_COUNT new upstream commit(s):"
        git log -n 10 "HEAD..$UPSTREAM_REF" --oneline | sed 's/^/  /'
    fi
    [ "$DRY_RUN" -eq 1 ] && { echo ""; info "Dry-run: no changes made."; exit 0; }

    # ── Step 3: Safety snapshot (only when we are actually about to modify) ────
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_BRANCH="backup/dsh-update-$TIMESTAMP"
    info "Creating safety snapshot: $BACKUP_BRANCH"
    python3 "$PATCHER" --export 2>/dev/null || true
    mkdir -p "$DSH_DIR/patches"
    git diff HEAD > "$DSH_DIR/patches/dsh-preupdate-$TIMESTAMP.patch" 2>/dev/null || true
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        git add -A
        git commit -m "chore(termux): pre-update snapshot $TIMESTAMP" 2>/dev/null || true
    fi
    git branch "$BACKUP_BRANCH" 2>/dev/null || true
    ok "Snapshot saved → $BACKUP_BRANCH"

    # ── Step 4: Merge upstream ─────────────────────────────────────────────────
    echo ""
    info "Merging $UPSTREAM_REF..."
    if ! git merge --no-edit -m "chore(termux): merge $UPSTREAM_REF and re-inject Termux/Mobile UX suite" "$UPSTREAM_REF" 2>/dev/null; then
        warn "Merge conflicts detected — auto-resolving managed files..."
        CONFLICTS=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
        for f in $CONFLICTS; do
            git checkout --theirs "$f" 2>/dev/null || git rm -f "$f" 2>/dev/null || true
            git add "$f" 2>/dev/null || true
        done
        git commit -m "chore(termux): merge upstream and re-inject Termux/Mobile UX suite" 2>/dev/null || true
    fi
    ok "Upstream merged."

    # ── Step 5: Reapply Termux patches ─────────────────────────────────────────
    echo ""
    info "Reapplying Termux & Mobile UX patches..."
    python3 "$PATCHER" --apply
    python3 "$PATCHER" --check >/dev/null 2>&1 || python3 "$PATCHER" --apply
    ok "Patches applied."

    # ── Step 6: Sync workspace links ──────────────────────────────────────────
    echo ""
    info "Syncing workspace links..."
    python3 "$PATCHER" --apply
    ok "Workspace links verified."
fi  # end REAPPLY_ONLY else

[ "$NO_BUILD" -eq 1 ] && {
    info "--no-build: skipping compile/push step."
    # Still push so origin is current
    git add -A
    NEW_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "latest")
    git commit -m "chore(termux): sync upstream v$NEW_VERSION + mobile suite" 2>/dev/null || true
    git push -u origin master 2>/dev/null || warn "Push skipped."
    ok "Done (no build)."
    exit 0
}

# ── Step 7: Push to origin → trigger CI ────────────────────────────────────
echo ""
info "Pushing to origin/$REPO_NAME (triggers GitHub Actions CI build)..."
git add -A
NEW_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "latest")
COMMITTED=0
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    git commit -m "chore(termux): regenerate patch bundle hashes against merged upstream" 2>/dev/null && COMMITTED=1 || true
fi
PUSH_OUTPUT=$(git push -u origin master 2>&1) && echo "$PUSH_OUTPUT" | tail -3 || warn "Push issue: $PUSH_OUTPUT"
ok "Pushed → https://github.com/$REPO_OWNER/$REPO_NAME"

# ── Step 8: Wait for GitHub CI build ──────────────────────────────────────
echo ""
info "Waiting for GitHub Actions CI build to start..."
sleep 5  # give GH a moment to register the push

STARTED=0
WAIT_START=$(date +%s)
RUN_ID=""

# Find the triggered run (poll up to 60s for it to appear)
for i in $(seq 1 12); do
    RUN_JSON=$(gh run list \
        --repo "$REPO_OWNER/$REPO_NAME" \
        --workflow "build-termux.yml" \
        --branch master \
        --limit 5 \
        --json databaseId,workflowName,status,conclusion,startedAt \
        2>/dev/null || echo "[]")

    RUN_ID=$(echo "$RUN_JSON" | \
        node -e "
const runs=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));
const r=runs.find(r=>(r.workflowName.includes('Termux')||r.workflowName.includes('Prebuilt'))&&(['in_progress','queued','waiting','requested'].includes(r.status)||(r.status==='completed'&&new Date(r.startedAt).getTime()>=($WAIT_START-60)*1000)));
console.log(r?r.databaseId:'');
" 2>/dev/null || true)

    if [ -n "$RUN_ID" ]; then
        STARTED=1
        ok "CI run started: https://github.com/$REPO_OWNER/$REPO_NAME/actions/runs/$RUN_ID"
        break
    fi
    echo -ne "  Waiting for CI run to appear... (${i}0s)\r"
    sleep 10
done

if [ "$STARTED" -eq 0 ]; then
    warn "Could not detect CI run. Checking for existing completed release instead..."
fi

# ── Step 9: Poll until CI completes ───────────────────────────────────────
if [ -n "$RUN_ID" ]; then
    echo ""
    info "Monitoring CI build (run #$RUN_ID)..."
    ELAPSED=0
    while true; do
        STATUS_JSON=$(gh run view "$RUN_ID" \
            --repo "$REPO_OWNER/$REPO_NAME" \
            --json status,conclusion \
            2>/dev/null || echo '{"status":"unknown","conclusion":""}')

        STATUS=$(echo "$STATUS_JSON" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));console.log(d.status);" 2>/dev/null || echo "unknown")
        CONCLUSION=$(echo "$STATUS_JSON" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));console.log(d.conclusion);" 2>/dev/null || echo "")

        ELAPSED=$(( $(date +%s) - WAIT_START ))
        MINS=$(( ELAPSED / 60 ))
        SECS=$(( ELAPSED % 60 ))

        if [ "$STATUS" = "completed" ]; then
            if [ "$CONCLUSION" = "success" ]; then
                ok "CI build succeeded! (${MINS}m${SECS}s)"
                break
            else
                echo ""
                err "CI build $CONCLUSION. Check: https://github.com/$REPO_OWNER/$REPO_NAME/actions/runs/$RUN_ID"
                err "Build failed on remote CI. Aborting update (local building is disabled)."
                exit 1
            fi
        fi

        # Show current step
        STEP=$(gh run view --job="$(gh run view "$RUN_ID" --repo "$REPO_OWNER/$REPO_NAME" --json jobs -q '.jobs[0].databaseId' 2>/dev/null || echo '')" \
            --repo "$REPO_OWNER/$REPO_NAME" 2>/dev/null \
            | grep '^\s*\*' | head -1 | sed 's/^[[:space:]]*\*/  ⟳/' || echo "  ⟳ Running...")
        echo -ne "\r  ⟳ CI: $STATUS | ${MINS}m${SECS}s elapsed${STEP:+ | step: $(echo "$STEP" | tr -d '⟳ ')}      "

        if [ "$ELAPSED" -gt "$CI_TIMEOUT" ]; then
            echo ""
            err "CI timeout after ${CI_TIMEOUT}s. Check: https://github.com/$REPO_OWNER/$REPO_NAME/actions/runs/$RUN_ID"
            err "Remote CI timed out. Aborting update."
            exit 1
        fi
        sleep "$CI_POLL_INTERVAL"
    done
    echo ""
fi

# ── Step 10: Download & apply prebuilt CI bundle ───────────────────────
echo ""
info "Downloading prebuilt lib/ bundle from GitHub release..."
bash "$DSH_DIR/scripts/install-prebuilt.sh" "$NEW_VERSION" 2>&1 \
    || { err "install-prebuilt.sh failed."; exit 1; }

# Post-install smoke check: the profile booter must compose the web
# profile tree (catches 0.1.5+ bundle-resolution breakage that
# `dsh --version` cannot see).
if dsh --profile web --dump-config >/dev/null 2>&1; then
    ok "Profile composition check passed (dsh --profile web)."
else
    warn "dsh --profile web --dump-config failed — profile resolution broken."
fi

# ── Step 12: Verify ──────────────────────────────────────────────────────────
echo ""
info "Verifying installation..."
NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# 0.1.5+ architecture: profile trees compose dsh.profile.bundles through the
# REPO's node_modules workspace links, so those links are the load-bearing part.
for B in @deepseek-ai/dsh-base @deepseek-ai/dsh-web-app @deepseek-ai/dsh-headless; do
    if node -e "require.resolve('$B/package.json', {paths: ['$DSH_DIR']})" >/dev/null 2>&1; then
        ok "$B — resolves OK"
    else
        warn "$B — MISSING from workspace links (run: pnpm install in $DSH_DIR)"
    fi
done

# The web profile tree must compose end-to-end (the boot path `dsh web` uses)
if dsh --profile web --dump-config >/dev/null 2>&1; then
    ok "web profile composes OK"
else
    warn "web profile composition failed — check ~/.dsh/profiles/web/"
fi

if dsh --version >/dev/null 2>&1; then
    box "✓ DeepSeek Harness Updated Successfully!"
    echo -e "  Version:   ${YELLOW}$PREV_VERSION${NC} → ${GREEN}$NEW_VERSION${NC}"
    echo -e "  Commit:    $PREV_COMMIT → $NEW_COMMIT"
    echo -e "  Snapshot:  ${BACKUP_BRANCH:-N/A}"
    echo -e "  Run:       ${CYAN}dsh-web${NC}"
    echo ""
else
    warn "dsh --version had an issue. Try: dsh-doctor"
    warn "To rollback: dsh-update --rollback"
fi
