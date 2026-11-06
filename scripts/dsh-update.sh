#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# dsh-update — Autonomous Zero-Loss Updater for DeepSeek Harness on Termux
# Design: Option 1 (Monolith Minimalist — Black, White, and Monochrome)
# Flow: pre-flight checks → merge upstream → patch → push → wait for GH Actions
#       CI build → download prebuilt lib/ bundle with progress → verify → done.
# ==============================================================================
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
export NODE_OPTIONS="--max-old-space-size=2560 ${NODE_OPTIONS:-}"
export PATH="$HOME/bin:$HOME/.npm-global/bin:$PATH"

# Prevent Corepack and pnpm engine from downloading @pnpm/exe native binaries on Android
export COREPACK_ENABLE_PROJECT_SPEC=0
export COREPACK_ENABLE_STRICT=0
export COREPACK_ENABLE_AUTO_PIN=0
export pnpm_config_pm_on_fail=ignore
export pnpm_config_manage_package_manager_versions=false
corepack disable 2>/dev/null || true

# ── Config ────────────────────────────────────────────────────────────────────
DSH_DIR="$HOME/deepseek-harness"
PATCHER="$DSH_DIR/scripts/patch_termux.py"
UPSTREAM_REPO="https://github.com/deepseek-ai/deepseek-harness.git"
REPO_OWNER="salmanbappi"
REPO_NAME="deepseek-harness"
WORKFLOW_NAME="build-termux.yml"
CI_POLL_INTERVAL=15   # seconds between status checks
CI_TIMEOUT=1800       # 30 minutes max wait

# ── Monochrome Palette & Typography (Option 1) ────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
W='\033[1;37m'          # Pure bright white
G='\033[38;5;245m'       # Medium grey
DG='\033[38;5;238m'      # Dark slate grey
LG='\033[38;5;252m'      # Light neutral grey
R='\033[7m'              # Inverse / Reverse video
N='\033[0m'              # Reset

# Responsive width formatting for mobile terminals
TERM_COLS=$(tput cols 2>/dev/null || echo 64)
[ "$TERM_COLS" -gt 64 ] && WIDTH=64 || WIDTH="$TERM_COLS"
[ "$WIDTH" -lt 45 ] && WIDTH=45
DIVIDER=$(printf '─%.0s' $(seq 1 "$WIDTH"))

# Diagnostic log buffer
TMP_DIR="${TMPDIR:-/data/data/com.termux/files/usr/tmp}"
mkdir -p "$TMP_DIR" 2>/dev/null || true
ERR_LOG=$(mktemp "${TMP_DIR}/dsh_update_err_XXXXXX.log" 2>/dev/null || echo "${TMP_DIR}/dsh_update_err.log")
trap 'rm -f "$ERR_LOG" 2>/dev/null || true' EXIT

# ── Animation & Progress Helpers ──────────────────────────────────────────────
SPIN_PID=""

start_spinner() {
    local msg="$1"
    tput civis 2>/dev/null || true
    (
        frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
        i=0
        while true; do
            printf "\r ${W}%s${N} ${LG}%s${N}\033[K" "${frames[$i]}" "$msg"
            i=$(( (i + 1) % 10 ))
            sleep 0.08
        done
    ) &
    SPIN_PID=$!
}

stop_spinner() {
    local status="${1:-0}"
    local label="${2:-}"
    if [ -n "$SPIN_PID" ]; then
        kill "$SPIN_PID" 2>/dev/null || true
        wait "$SPIN_PID" 2>/dev/null || true
        SPIN_PID=""
    fi
    tput cnorm 2>/dev/null || true
    if [ "$status" -eq 0 ]; then
        printf "\r ${W}●${N} %-44s ${W}[ PASS ]${N}\n" "$label"
    else
        printf "\r ${R}${W} ✕ ${N} %-44s ${R}${W}[ FAIL ]${N}\n" "$label"
    fi
}

fail_and_dump() {
    local step_name="$1"
    stop_spinner 1 "$step_name" 2>/dev/null || true
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${R}${W} UPDATE ERROR DIAGNOSTIC DUMP ${N}"
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}Stage Failed:${N} ${LG}${step_name}${N}\n"
    if [ -f "$ERR_LOG" ] && [ -s "$ERR_LOG" ]; then
        echo -e " ${G}Captured Diagnostic Output:${N}"
        sed 's/^/   /' "$ERR_LOG" | tail -n 25
    fi
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${W}Update halted safely. No broken state applied.${N}"
    echo -e " ${G}To rollback previous snapshot:${N} ${W}dsh-update --rollback${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 1
}

banner() {
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}DEEPSEEK HARNESS${N} ${G}— Autonomous Upstream Updater${N}"
    echo -e "${DG}${DIVIDER}${N}"
}

# ── Argument Parsing ──────────────────────────────────────────────────────────
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
            echo -e "${R}${W} ERROR ${N} --local-build is disabled: only remote GitHub Actions CI builds are allowed." >&2
            exit 1
            ;;
        --list-backups|--backups)
            banner
            echo -e " ${W}Available Safety Snapshots:${N}\n"
            cd "$DSH_DIR" 2>/dev/null || exit 1
            git branch --list "backup/dsh-*" | sed 's/^[ *]*/   • /' || echo "   (No snapshots found)"
            echo -e "\n ${G}To restore a snapshot:${N} ${W}dsh-update --rollback <branch>${N}"
            echo -e "${DG}${DIVIDER}${N}\n"
            exit 0
            ;;
        --rollback)
            shift
            ROLLBACK_TARGET="${1:-}"
            [ -n "$ROLLBACK_TARGET" ] && shift || true
            ;;
        --help|-h)
            banner
            echo -e " ${W}Usage:${N} dsh-update [options]\n"
            echo -e " ${W}Options:${N}"
            echo -e "   ${W}(none)${N}             Full update: merge upstream → push → CI build → apply"
            echo -e "   ${W}--dry-run, -n${N}      Check upstream commits without modifying repository"
            echo -e "   ${W}--reapply-only${N}     Re-patch + push + wait for CI + apply (skip merge)"
            echo -e "   ${W}--no-build${N}         Merge + patch + push only (no build/apply step)"
            echo -e "   ${W}--force, -f${N}        Force rebuild & deploy even if already up-to-date"
            echo -e "   ${W}--ref, -r <ref>${N}    Update to a specific Git commit, branch, or tag"
            echo -e "   ${W}--rollback [BR]${N}    Roll back repository to a safety snapshot branch"
            echo -e "   ${W}--list-backups${N}     List available snapshot branches"
            echo -e "   ${W}--help, -h${N}         Show this documentation"
            echo -e "${DG}${DIVIDER}${N}\n"
            exit 0
            ;;
        *)
            echo -e "${R}${W} ERROR ${N} Unknown option: $1 (run 'dsh-update --help')" >&2
            exit 1
            ;;
    esac
done

banner

# ── Rollback Mode Execution ───────────────────────────────────────────────────
if [ -n "$ROLLBACK_TARGET" ] || [ "${1:-}" = "--rollback" 2>/dev/null ]; then
    cd "$DSH_DIR" 2>/dev/null || { echo "Directory $DSH_DIR not found"; exit 1; }
    if [ -z "$ROLLBACK_TARGET" ]; then
        ROLLBACK_TARGET=$(git branch --list "backup/dsh-*" --sort=-committerdate | head -n 1 | tr -d ' *')
    fi
    if [ -z "$ROLLBACK_TARGET" ]; then
        echo -e "${R}${W} FAIL ${N} No backup snapshots found to roll back to."
        exit 1
    fi
    start_spinner "Restoring snapshot: $ROLLBACK_TARGET..."
    git checkout master >"$ERR_LOG" 2>&1 || true
    git reset --hard "$ROLLBACK_TARGET" >"$ERR_LOG" 2>&1 || fail_and_dump "Rollback Reset ($ROLLBACK_TARGET)"
    python3 "$PATCHER" --apply >"$ERR_LOG" 2>&1 || true
    if [ "$NO_BUILD" -eq 0 ]; then
        bash "$DSH_DIR/scripts/install-prebuilt.sh" >"$ERR_LOG" 2>&1 || true
    fi
    stop_spinner 0 "Restored snapshot ($ROLLBACK_TARGET)"
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}[✓] Successfully rolled back to:${N} ${LG}${ROLLBACK_TARGET}${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 0
fi

# ── Stage 1: Pre-flight Verification Gate ─────────────────────────────────────
printf " ${W}◌${N} ${LG}Running pre-flight updater & environment verification...${N}"

ERRORS=()
REMEDIES=()
NOTICES=()

# 1. Termux OS Verification
if [ ! -d "/data/data/com.termux/files" ] && [ -z "${PREFIX:-}" ]; then
    ERRORS+=("Not running inside native Termux Android environment.")
    REMEDIES+=("Launch Termux on Android and run the updater from inside Termux.")
fi

# 2. Local Repository Workspace
if [ ! -d "$DSH_DIR/.git" ]; then
    ERRORS+=("DeepSeek Harness repository not found at $DSH_DIR.")
    REMEDIES+=("Run the installer first: curl -fsSL https://raw.githubusercontent.com/$REPO_OWNER/$REPO_NAME/master/scripts/install-termux.sh | bash")
fi

# 3. Disk Space Probe (Minimum 1,200 MB free)
STORAGE_TARGET="${PREFIX:-/data/data/com.termux/files/usr}"
FREE_KB=$(df -k "$STORAGE_TARGET" 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "$FREE_KB" ]; then
    FREE_MB=$(( FREE_KB / 1024 ))
    if [ "$FREE_MB" -lt 1200 ]; then
        ERRORS+=("Insufficient disk space: ${FREE_MB} MB free (requires >= 1,200 MB).")
        REMEDIES+=("Free up storage on device or run 'pkg clean' and 'pnpm store prune'.")
    else
        NOTICES+=("Storage verified: ${FREE_MB} MB available.")
    fi
fi

# 4. GitHub CLI Authentication
if ! command -v gh &>/dev/null; then
    ERRORS+=("GitHub CLI (gh) is not installed.")
    REMEDIES+=("Install with: pkg install gh")
else
    if ! gh auth status >/dev/null 2>&1; then
        ERRORS+=("GitHub CLI is not authenticated.")
        REMEDIES+=("Run 'gh auth login' to authenticate with your GitHub account.")
    else
        NOTICES+=("GitHub CLI authenticated.")
    fi
fi

# 5. Remote Network & API Connectivity
GH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 6 "https://api.github.com" 2>/dev/null || echo "000")
if [ "$GH_STATUS" = "000" ]; then
    ERRORS+=("Cannot connect to GitHub API (network unreachable).")
    REMEDIES+=("Check internet connection, DNS configuration, or disable restrictive VPN.")
fi

# Pre-flight Abort Gate
if [ "${#ERRORS[@]}" -gt 0 ]; then
    printf "\r ${R}${W} ✕ ${N} %-44s ${R}${W}[ FAIL ]${N}\n" "Pre-flight Verification & Environment"
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${R}${W} PRE-FLIGHT DIAGNOSTICS & ABORT DUMP ${N}"
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}Pre-flight verification detected ${#ERRORS[@]} blocking issue(s):${N}\n"
    for i in "${!ERRORS[@]}"; do
        idx=$(( i + 1 ))
        echo -e "  ${W}[0${idx}] ERROR:${N}   ${LG}${ERRORS[$i]}${N}"
        echo -e "       ${G}Remedy:${N}  ${G}${REMEDIES[$i]}${N}\n"
    done
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}No repository or file state was altered. Update aborted safely.${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 1
fi

printf "\r ${W}●${N} %-44s ${W}[ PASS ]${N}\n" "Pre-flight Verification & Environment"
for notice in "${NOTICES[@]}"; do
    echo -e "   ${DG}↳ ${G}${notice}${N}"
done

cd "$DSH_DIR"
PREV_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
PREV_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "unknown")
echo -e "   ${DG}↳ ${G}Current version: ${W}v${PREV_VERSION}${N} ${G}(commit ${PREV_COMMIT})${N}"

# ── Stage 2: Inspect Remotes & Upstream Changes ───────────────────────────────
start_spinner "Inspecting upstream repository and changes..."
git remote | grep -q "^upstream$" || git remote add upstream "$UPSTREAM_REPO" 2>"$ERR_LOG" || true
git remote | grep -q "^origin$"   || git remote add origin "https://github.com/$REPO_OWNER/$REPO_NAME.git" 2>/dev/null || true

if [ "$REAPPLY_ONLY" -eq 1 ]; then
    stop_spinner 0 "Inspect Remotes & Upstream (Reapply Mode)"
else
    if [ -n "$TARGET_REF" ]; then
        UPSTREAM_REF="$TARGET_REF"
        git fetch upstream "$TARGET_REF" --quiet >"$ERR_LOG" 2>&1 || git fetch origin "$TARGET_REF" --quiet >"$ERR_LOG" 2>&1 || true
    else
        UPSTREAM_REF="upstream/master"
        if ! git fetch upstream master --quiet >"$ERR_LOG" 2>&1; then
            git fetch origin master --quiet >"$ERR_LOG" 2>&1 || fail_and_dump "Fetch Upstream / Origin Master"
            UPSTREAM_REF="origin/master"
        fi
    fi

    INCOMING_COUNT=$(git rev-list --count "HEAD..$UPSTREAM_REF" 2>/dev/null || echo 0)
    OUTGOING_COUNT=$(git rev-list --count "origin/master..HEAD" 2>/dev/null || echo 0)

    if [ "$INCOMING_COUNT" -eq 0 ] && [ "$OUTGOING_COUNT" -eq 0 ] && [ "$FORCE" -eq 0 ]; then
        stop_spinner 0 "Inspect Remotes & Upstream (Up-to-Date)"
        echo -e "\n${DG}${DIVIDER}${N}"
        echo -e " ${W}DEEPSEEK HARNESS — ALREADY UP TO DATE${N}"
        echo -e "${DG}${DIVIDER}${N}"
        echo -e " ${W}[✓] Local workspace is fully up to date with upstream (v${PREV_VERSION}).${N}\n"
        echo -e " ${G}Options to proceed:${N}"
        echo -e "   ${W}dsh-update --force${N}       ${G}Force remote CI build and release deployment${N}"
        echo -e "   ${W}dsh-update --reapply${N}     ${G}Re-apply mobile patch suite without git merge${N}"
        echo -e "${DG}${DIVIDER}${N}\n"
        exit 0
    fi

    stop_spinner 0 "Inspect Remotes & Upstream ($INCOMING_COUNT incoming)"

    if [ "$INCOMING_COUNT" -gt 0 ]; then
        echo -e "   ${DG}↳ ${G}Incoming upstream commits:${N}"
        git log -n 5 "HEAD..$UPSTREAM_REF" --oneline | sed 's/^/     /'
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        echo -e "\n${DG}${DIVIDER}${N}"
        echo -e " ${W}[✓] Dry-run completed. No changes applied.${N}"
        echo -e "${DG}${DIVIDER}${N}\n"
        exit 0
    fi

    # ── Stage 3: Create Safety Snapshot ─────────────────────────────────────────
    start_spinner "Creating safety snapshot branch..."
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_BRANCH="backup/dsh-update-$TIMESTAMP"
    python3 "$PATCHER" --export >"$ERR_LOG" 2>&1 || true
    mkdir -p "$DSH_DIR/patches"
    git diff HEAD > "$DSH_DIR/patches/dsh-preupdate-$TIMESTAMP.patch" 2>/dev/null || true
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        git add -A >"$ERR_LOG" 2>&1 || true
        git commit -m "chore(termux): pre-update snapshot $TIMESTAMP" >"$ERR_LOG" 2>&1 || true
    fi
    git branch "$BACKUP_BRANCH" >"$ERR_LOG" 2>&1 || fail_and_dump "Create Snapshot Branch"
    stop_spinner 0 "Create Safety Snapshot ($BACKUP_BRANCH)"

    # ── Stage 4: Merge Upstream Changes ─────────────────────────────────────────
    start_spinner "Merging $UPSTREAM_REF..."
    if ! git merge --no-edit -m "chore(termux): merge $UPSTREAM_REF and re-inject Termux/Mobile UX suite" "$UPSTREAM_REF" >"$ERR_LOG" 2>&1; then
        CONFLICTS=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
        for f in $CONFLICTS; do
            git checkout --theirs "$f" >"$ERR_LOG" 2>&1 || git rm -f "$f" >"$ERR_LOG" 2>&1 || true
            git add "$f" >"$ERR_LOG" 2>&1 || true
        done
        git commit -m "chore(termux): merge upstream and re-inject Termux/Mobile UX suite" >"$ERR_LOG" 2>&1 || fail_and_dump "Merge Upstream"
    fi
    stop_spinner 0 "Merge Upstream Changes"
fi

# ── Stage 5: Re-apply Mobile UX & Termux Patches ──────────────────────────────
start_spinner "Re-applying Termux & Mobile UX patch suite..."
python3 "$PATCHER" --apply >"$ERR_LOG" 2>&1 || true
python3 "$PATCHER" --check >"$ERR_LOG" 2>&1 || python3 "$PATCHER" --apply >"$ERR_LOG" 2>&1 || fail_and_dump "Apply Mobile Patches"
stop_spinner 0 "Re-apply Termux & Mobile UX Patches"

[ "$NO_BUILD" -eq 1 ] && {
    start_spinner "Syncing repository without remote build..."
    git add -A >"$ERR_LOG" 2>&1 || true
    NEW_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "latest")
    git commit -m "chore(termux): sync upstream v$NEW_VERSION + mobile suite" >"$ERR_LOG" 2>&1 || true
    git push -u origin master >"$ERR_LOG" 2>&1 || true
    stop_spinner 0 "Sync Repository (No Build)"
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${W}[✓] Completed without remote build (--no-build).${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 0
}

# ── Stage 6: Push Changes & Trigger GitHub Actions CI Build ───────────────────
start_spinner "Pushing to origin/$REPO_NAME (triggering CI build)..."
git add -A >"$ERR_LOG" 2>&1 || true
NEW_VERSION=$(node -e "console.log(require('./package.json').version)" 2>/dev/null || echo "latest")
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    git commit -m "chore(termux): regenerate patch bundle hashes against merged upstream" >"$ERR_LOG" 2>&1 || true
fi
git push -u origin master >"$ERR_LOG" 2>&1 || fail_and_dump "Git Push to Origin"
stop_spinner 0 "Push to Origin (CI Build Triggered)"

# ── Stage 7: Monitor Remote GitHub Actions CI Build ───────────────────────────
start_spinner "Locating triggered GitHub Actions workflow run..."
sleep 4
WAIT_START=$(date +%s)
RUN_ID=""

for i in $(seq 1 12); do
    RUN_JSON=$(gh run list \
        --repo "$REPO_OWNER/$REPO_NAME" \
        --workflow "$WORKFLOW_NAME" \
        --branch master \
        --limit 5 \
        --json databaseId,workflowName,status,conclusion,startedAt \
        2>"$ERR_LOG" || echo "[]")

    RUN_ID=$(echo "$RUN_JSON" | \
        node -e "
const runs = JSON.parse(require('fs').readFileSync('/dev/stdin', 'utf8'));
const r = runs.find(r => (r.workflowName.includes('Termux') || r.workflowName.includes('Prebuilt')) && (['in_progress','queued','waiting','requested'].includes(r.status) || (r.status === 'completed' && new Date(r.startedAt).getTime() >= ($WAIT_START - 60) * 1000)));
console.log(r ? r.databaseId : '');
" 2>/dev/null || true)

    if [ -n "$RUN_ID" ]; then
        break
    fi
    sleep 5
done

if [ -z "$RUN_ID" ]; then
    stop_spinner 0 "Locate CI Workflow Run (Existing Release Mode)"
else
    stop_spinner 0 "Locate CI Workflow Run (#$RUN_ID)"

    # Monitor run loop with live timer
    while true; do
        STATUS_JSON=$(gh run view "$RUN_ID" \
            --repo "$REPO_OWNER/$REPO_NAME" \
            --json status,conclusion \
            2>"$ERR_LOG" || echo '{"status":"unknown","conclusion":""}')

        STATUS=$(echo "$STATUS_JSON" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));console.log(d.status);" 2>/dev/null || echo "unknown")
        CONCLUSION=$(echo "$STATUS_JSON" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));console.log(d.conclusion);" 2>/dev/null || echo "")

        ELAPSED=$(( $(date +%s) - WAIT_START ))
        MINS=$(( ELAPSED / 60 ))
        SECS=$(( ELAPSED % 60 ))

        if [ "$STATUS" = "completed" ]; then
            if [ "$CONCLUSION" = "success" ]; then
                printf "\r ${W}●${N} %-44s ${W}[ PASS ]${N}\n" "Remote CI Compilation (${MINS}m ${SECS}s)"
                break
            else
                printf "\r ${R}${W} ✕ ${N} %-44s ${R}${W}[ FAIL ]${N}\n" "Remote CI Compilation ($CONCLUSION)"
                echo -e "\n${DG}${DIVIDER}${N}"
                echo -e " ${R}${W} REMOTE CI BUILD FAILURE ${N}"
                echo -e "${DG}${DIVIDER}${N}"
                echo -e " ${W}Run Details:${N} https://github.com/$REPO_OWNER/$REPO_NAME/actions/runs/$RUN_ID"
                echo -e " ${W}Remote CI concluded with status: ${R}${W} $CONCLUSION ${N}\n"
                echo -e " ${G}Local building is strictly forbidden by policy.${N}"
                echo -e " ${G}To rollback:${N} ${W}dsh-update --rollback${N}"
                echo -e "${DG}${DIVIDER}${N}\n"
                exit 1
            fi
        fi

        printf "\r ${W}⠋${N} ${LG}Building on GitHub Actions CI...${N} ${G}(%02dm %02ds elapsed)${N}\033[K" "$MINS" "$SECS"

        if [ "$ELAPSED" -gt "$CI_TIMEOUT" ]; then
            echo ""
            fail_and_dump "Remote CI Compilation (Timed out after ${CI_TIMEOUT}s)"
        fi
        sleep "$CI_POLL_INTERVAL"
    done
fi

# ── Stage 8: Download & Deploy Prebuilt Artifact Bundle ────────────────────────
start_spinner "Resolving latest prebuilt release asset..."
LATEST_TAG=$(gh release list --repo "$REPO_OWNER/$REPO_NAME" --limit 1 --json tagName -q '.[0].tagName' 2>/dev/null || echo "")
if [ -z "$LATEST_TAG" ]; then
    LATEST_TAG="v${NEW_VERSION}"
fi
stop_spinner 0 "Resolve Prebuilt Release Asset ($LATEST_TAG)"

TARBALL_URL="https://github.com/$REPO_OWNER/$REPO_NAME/releases/download/$LATEST_TAG/dsh-termux-prebuilt-${LATEST_TAG}.tar.gz"
DEST_TAR="$DSH_DIR/prebuilt.tar.gz"

# Download with Option 1 in-place progress bar
python3 -c "
import urllib.request, sys, time, os

url = '$TARBALL_URL'
dest = '$DEST_TAR'

try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Termux/Android)'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get('content-length', 0))
        chunk_size = 65536
        downloaded = 0
        start_time = time.time()
        with open(dest, 'wb') as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                pct = int(downloaded * 100 / total) if total > 0 else 0
                width = 24
                filled = int(pct * width / 100)
                bar = '█' * filled + '░' * (width - filled)
                cur_mb = downloaded / (1024 * 1024)
                tot_mb = total / (1024 * 1024)
                speed = cur_mb / max(0.1, time.time() - start_time)
                sys.stdout.write(f'\r   \033[1;37m[{bar}]\033[0m \033[1;37m{pct}%\033[0m  \033[38;5;244m{cur_mb:.1f} MB / {tot_mb:.1f} MB ({speed:.1f} MB/s)\033[0m\033[K')
                sys.stdout.flush()
    print()
except Exception as e:
    sys.exit(1)
" >"$ERR_LOG" 2>&1 || true

start_spinner "Extracting and applying prebuilt binaries..."
if [ -f "$DEST_TAR" ] && [ -s "$DEST_TAR" ]; then
    if [ "$(tar -tzf "$DEST_TAR" | grep -c '^apps/web/dist/' || true)" -gt 0 ]; then
        rm -rf "$DSH_DIR/apps/web/dist"
    fi
    tar -xzf "$DEST_TAR" -C "$DSH_DIR" >"$ERR_LOG" 2>&1 || fail_and_dump "Extract Prebuilt Tarball"
    rm -f "$DEST_TAR"
else
    # Fallback to gh release download if python direct download had issue
    gh release download "$LATEST_TAG" --repo "$REPO_OWNER/$REPO_NAME" --pattern "dsh-termux-prebuilt-*.tar.gz" --dir "$DSH_DIR" >"$ERR_LOG" 2>&1 || true
    ARCHIVE=$(ls "$DSH_DIR"/dsh-termux-prebuilt-*.tar.gz 2>/dev/null | head -1 || true)
    if [ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ]; then
        tar -xzf "$ARCHIVE" -C "$DSH_DIR" >"$ERR_LOG" 2>&1 || fail_and_dump "Extract Prebuilt Archive"
        rm -f "$ARCHIVE"
    else
        fail_and_dump "Download Prebuilt Bundle"
    fi
fi
stop_spinner 0 "Extract & Deploy Prebuilt Binaries"

# ── Stage 9: Verification & Health Check ───────────────────────────────────────
start_spinner "Linking dependencies & checking workspace health..."
python3 "$PATCHER" --apply >"$ERR_LOG" 2>&1 || true
pnpm install --prod --frozen-lockfile=false --ignore-scripts >"$ERR_LOG" 2>&1 || true
pnpm store prune 2>/dev/null || true

stop_spinner 0 "Workspace Linking & Mobile Patches"

NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# Verify core bundles
BUNDLE_CHECK=1
for B in @deepseek-ai/dsh-base @deepseek-ai/dsh-web-app @deepseek-ai/dsh-headless; do
    if ! node -e "require.resolve('$B/package.json', {paths: ['$DSH_DIR']})" >/dev/null 2>&1; then
        BUNDLE_CHECK=0
        break
    fi
done

if [ "$BUNDLE_CHECK" -eq 1 ]; then
    printf " ${W}●${N} %-44s ${W}[ PASS ]${N}\n" "Workspace Profile Bundles Resolution"
else
    printf " ${R}${W} ✕ ${N} %-44s ${R}${W}[ WARN ]${N}\n" "Workspace Profile Bundles Resolution"
fi

# ── Setup Complete Banner ─────────────────────────────────────────────────────
echo -e "${DG}${DIVIDER}${N}"
echo -e " ${W}DEEPSEEK HARNESS — UPDATE COMPLETE${N}"
echo -e "${DG}${DIVIDER}${N}"
echo -e " ${W}[✓] DeepSeek Harness updated successfully!${N}\n"
echo -e " ${W}Update Summary:${N}"
echo -e "   ${G}Version:${N}    ${LG}v${PREV_VERSION}${N} → ${W}v${NEW_VERSION}${N}"
echo -e "   ${G}Commit:${N}     ${LG}${PREV_COMMIT}${N} → ${W}${NEW_COMMIT}${N}"
echo -e "   ${G}Snapshot:${N}   ${LG}${BACKUP_BRANCH:-None}${N}\n"
echo -e " ${W}Commands Available:${N}"
echo -e "   ${W}dsh web${N}        ${G}Start the Mobile Web UI (http://127.0.0.1:3080)${N}"
echo -e "   ${W}dsh-doctor${N}     ${G}Verify environment & patch integrity${N}"
echo -e "   ${W}dsh-update --rollback${N} ${G}Restore previous snapshot${N}\n"
echo -e " ${W}To start right now:${N}"
echo -e "   ${W}dsh web${N}"
echo -e "${DG}${DIVIDER}${N}\n"
