#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
#  DeepSeek Harness — Automated 1-Line Termux & Mobile Installer
#  Repository: https://github.com/salmanbappi/deepseek-harness
#  Design: Option 1 (Monolith Minimalist — Black, White, and Monochrome)
# ==============================================================================
set -euo pipefail

# A pipe feeds the shell bytes as they arrive, so a connection that drops
# mid-line surfaces as `syntax error near unexpected token` from a fragment
# rather than as a download failure. Reading this script from disk first, and
# re-executing that copy, turns a short read into one clear message.
# BASH_SOURCE is unset only when the script arrives on stdin.
if [ -z "${BASH_SOURCE[0]:-}" ]; then
    SELF_DL="${TMPDIR:-${PREFIX:-/tmp}}/dsh-install-$$.sh"
    SELF_OK=0
    # Several sources, because one CDN edge can serve a stale branch snapshot
    # for an unbounded time while another already has the current file. Any
    # copy that parses and carries the sentinel below is accepted.
    for SELF_URL in \
        "https://raw.githubusercontent.com/salmanbappi/deepseek-harness/refs/heads/master/scripts/install-termux.sh" \
        "https://raw.githubusercontent.com/salmanbappi/deepseek-harness/master/scripts/install-termux.sh" \
        "https://cdn.jsdelivr.net/gh/salmanbappi/deepseek-harness@master/scripts/install-termux.sh"
    do
        if curl -fsSL --retry 2 --retry-delay 2 --connect-timeout 15 "$SELF_URL" -o "$SELF_DL" \
            && [ "$(wc -c <"$SELF_DL" 2>/dev/null || echo 0)" -ge 20000 ] \
            && grep -q "dsh-installer-sentinel" "$SELF_DL" \
            && bash -n "$SELF_DL" 2>/dev/null; then
            SELF_OK=1
            break
        fi
    done
    if [ "$SELF_OK" -eq 1 ]; then
        # exec replaces this process, so the rm below never runs on the success
        # path; hand the path to the re-executed copy, which removes it on exit.
        export DSH_INSTALL_SELF="$SELF_DL"
        exec bash "$SELF_DL" "$@"
    fi
    rm -f "$SELF_DL"
    echo "install-termux: could not fetch a complete copy over this connection."
    echo "Retry, or download it first and run it from the file:"
    echo "  curl -fsSLo install-termux.sh https://raw.githubusercontent.com/salmanbappi/deepseek-harness/refs/heads/master/scripts/install-termux.sh"
    echo "  bash install-termux.sh"
    exit 1
fi
# dsh-installer-sentinel: marks a complete copy of this script. The piped-input
# branch above requires it, so a truncated or stale fetch is rejected instead of
# executed.


export DEBIAN_FRONTEND=noninteractive
# Size the heap to the device rather than to a desktop default. 2560 MB exceeds
# the free memory on a 2 GB phone, where V8 will grow toward the ceiling and can
# take the whole device down before it collects. Override with DSH_MAX_OLD_SPACE.
_dsh_total_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null)
case "$_dsh_total_mb" in ''|*[!0-9]*) _dsh_total_mb=2048;; esac
if [ "$_dsh_total_mb" -ge 3500 ]; then _dsh_space=1536
elif [ "$_dsh_total_mb" -ge 2500 ]; then _dsh_space=1024
else _dsh_space=768
fi
export NODE_OPTIONS="--max-old-space-size=${DSH_MAX_OLD_SPACE:-$_dsh_space} ${NODE_OPTIONS:-}"
unset _dsh_total_mb _dsh_space
export PATH="$HOME/bin:$HOME/.npm-global/bin:$PATH"
# Prevent Corepack and pnpm engine from downloading @pnpm/exe native binaries on Android
export COREPACK_ENABLE_PROJECT_SPEC=0
export COREPACK_ENABLE_STRICT=0
export COREPACK_ENABLE_AUTO_PIN=0
export pnpm_config_pm_on_fail=ignore
export pnpm_config_manage_package_manager_versions=false
corepack disable 2>/dev/null || true

# ── Monochrome Palette & Typography (Option 1) ────────────────────────────────
# Emit escape sequences only when stdout is a terminal that can render them.
# Piped, redirected, or pasted output keeps the bare text instead of the codes,
# and a terminal without 256-colour support falls back to basic attributes.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
    case "$(tput colors 2>/dev/null || echo 0)" in
        256|32767)
            BOLD='\033[1m'; DIM='\033[2m'
            W='\033[1;37m'; G='\033[38;5;245m'; DG='\033[38;5;238m'; LG='\033[38;5;252m'
            R='\033[7m'; N='\033[0m'
            ;;
        8|16)
            BOLD='\033[1m'; DIM='\033[2m'
            W='\033[1;37m'; G='\033[0;37m'; DG='\033[0;37m'; LG='\033[0;37m'
            R='\033[7m'; N='\033[0m'
            ;;
        *)  BOLD=''; DIM=''; W=''; G=''; DG=''; LG=''; R=''; N='' ;;
    esac
else
    BOLD=''; DIM=''; W=''; G=''; DG=''; LG=''; R=''; N=''
fi

# Responsive width formatting for mobile terminals
# Clear-to-end-of-line is also a terminal-only sequence.
CLR=''
export DSH_CLR=''
if [ -n "$N" ]; then
    CLR='\033[K'
    export DSH_CLR="$CLR"
fi

TERM_COLS=$(tput cols 2>/dev/null || echo 64)
[ "$TERM_COLS" -gt 64 ] && WIDTH=64 || WIDTH="$TERM_COLS"
[ "$WIDTH" -lt 45 ] && WIDTH=45
DIVIDER=$(printf '─%.0s' $(seq 1 "$WIDTH"))

# Diagnostic log buffer
TMP_DIR="${TMPDIR:-/data/data/com.termux/files/usr/tmp}"
mkdir -p "$TMP_DIR" 2>/dev/null || true
ERR_LOG=$(mktemp "${TMP_DIR}/dsh_install_err_XXXXXX.log" 2>/dev/null || echo "${TMP_DIR}/dsh_install_err.log")
trap 'rm -f "$ERR_LOG" 2>/dev/null || true' EXIT
# Set by the stdin self-refetch above; this copy owns removing the file it was
# executed from, since the process that wrote it was replaced by exec.
if [ -n "${DSH_INSTALL_SELF:-}" ]; then
    trap 'rm -f "$ERR_LOG" "$DSH_INSTALL_SELF" 2>/dev/null || true' EXIT
fi

# ── Animation & Progress Helpers ──────────────────────────────────────────────
SPIN_PID=""

start_spinner() {
    local msg="$1"
    # A spinner is only informative on a terminal. When stdout is a pipe, a log,
    # or a CI capture, every frame is appended instead of overwriting the last
    # one, so a 12 fps loop turns a multi-minute install into thousands of lines
    # of the same message. Print the step once and skip the animation.
    if [ -z "$N" ]; then
        printf " • %s\n" "$msg"
        return 0
    fi
    tput civis 2>/dev/null || true
    (
        frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
        i=0
        while true; do
            printf "\r ${W}%s${N} ${LG}%s${N}%s" "${frames[$i]}" "$msg" "$CLR"
            i=$(( (i + 1) % 10 ))
            # 0.2s keeps the motion legible while cutting terminal writes to
            # under half; the phone pays for each one in wakeups.
            sleep 0.2
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
    # Without colour there is no spinner to overwrite, so the step line stands
    # on its own rather than being redrawn with a verdict glyph.
    if [ -z "$N" ]; then
        if [ "$status" -eq 0 ]; then
            printf "   %s\n" "$label"
        else
            printf "   %s\n" "$label"
        fi
        return 0
    fi
    if [ "$status" -eq 0 ]; then
        printf "\r ${W}●${N} %s ${W}OK${N}\n" "$label"
    else
        printf "\r ${R}${W} ✕${N} %s ${R}${W}FAILED${N}\n" "$label"
    fi
}

# ── Visible-transfer helper ───────────────────────────────────────────────────
# git and curl report throughput on stderr, which the spinner and the shared
# error log both hide: a 48 MB clone on mobile data then looks identical to a
# hang, and the only way to tell them apart is to time it. Run these transfers
# with the spinner stopped and a transfer meter on screen instead, so a slow
# link shows its rate and a stalled one is visibly stalled.
#
# git writes progress to stderr only when it believes a terminal is attached,
# so the command is run under a pseudo-terminal. The full output still lands in
# ERR_LOG for fail_and_dump.
run_with_progress() {
    local label="$1"; shift
    # Retire the spinner by name only: a PASS line here would be a lie if the
    # transfer then fails, and the caller prints the real verdict afterwards.
    if [ -n "$SPIN_PID" ]; then
        kill "$SPIN_PID" 2>/dev/null || true
        wait "$SPIN_PID" 2>/dev/null || true
        SPIN_PID=""
    fi
    tput cnorm 2>/dev/null || true
    printf "\r ${W}●${N} %s\n" "$label"
    echo -e "   ${DG}transferring — rate below; no output for 60s means stalled${N}"

    local rc=0
    if command -v script >/dev/null 2>&1; then
        # `script` gives git a tty so --progress renders. -q keeps it quiet
        # about itself. -e is required: without it `script` exits 0 whatever the
        # child did, so a failed clone reads as success and the retry loop never
        # retries.
        #
        # The command is passed as a single string because that is all `script`
        # accepts, so each argument is quoted for the shell that re-parses it.
        # Joining with `"$*"` would split any path containing a space.
        local quoted
        quoted=$(printf '%q ' "$@")
        script -q -e -c "$quoted" /dev/null 2>&1 | tee -a "$ERR_LOG"
        rc=${PIPESTATUS[0]}
    else
        # Without `script` the transfer still runs; git only omits its meter.
        GIT_PROGRESS_DELAY=0 "$@" 2>&1 | tee -a "$ERR_LOG"
        rc=${PIPESTATUS[0]}
    fi
    return "$rc"
}

# Run a long install command that would otherwise sit silent for many minutes.
#
# A production install resolves thousands of packages, so the step is genuinely
# slow on mobile data — and when its output goes to a log the screen shows
# nothing at all, which reads as a hang. Unlike a download there is no byte
# meter to show, so this prints a heartbeat proving the step is alive, and
# enforces a deadline so a genuinely stalled install fails instead of spinning
# forever.
run_install_step() {
    local label="$1" timeout_s="$2"; shift 2
    local log="$ERR_LOG"
    # On a terminal the heartbeat overwrites its own line; off one there is
    # nothing to overwrite, so it prints at a much lower rate instead of
    # appending a line every tick.
    local HB_CR=''
    if [ -n "$N" ]; then
        HB_CR='\r'
        printf "   %s\n" "$label"
        printf "     (this downloads many packages and can take 10+ minutes)\n"
    else
        printf "   %s (may take 10+ minutes; progress is in the install log)\n" "$label"
    fi

    local start elapsed rc=0
    local tick=2
    [ -n "$N" ] || tick=30
    start=$(date +%s)

    # Own process group, so the deadline can stop the whole tree. Signalling only
    # the direct child leaves pnpm's workers and extractors running: the install
    # would keep writing into node_modules after this reported it had stopped.
    set -m
    "$@" >>"$log" 2>&1 &
    local cmd_pid=$!
    set +m

    local elapsed_at_tick=0
    while kill -0 "$cmd_pid" 2>/dev/null; do
        elapsed=$(( $(date +%s) - start ))
        if [ "$elapsed" -ge "$timeout_s" ]; then
            # Ask first, then insist. A worker that traps TERM would otherwise
            # keep the `wait` below blocked forever, so the deadline would never
            # be reported and the install would appear to hang.
            kill -TERM -- -"$cmd_pid" 2>/dev/null || kill -TERM "$cmd_pid" 2>/dev/null || true
            local grace=0
            while kill -0 "$cmd_pid" 2>/dev/null && [ "$grace" -lt 10 ]; do
                sleep 1
                grace=$(( grace + 1 ))
            done
            if kill -0 "$cmd_pid" 2>/dev/null; then
                kill -KILL -- -"$cmd_pid" 2>/dev/null || kill -KILL "$cmd_pid" 2>/dev/null || true
            fi
            wait "$cmd_pid" 2>/dev/null || true
            printf "%s     stopped after %dm%02ds (limit reached)\n" "$HB_CR" \
                $(( elapsed / 60 )) $(( elapsed % 60 ))
            return 124
        fi
        # Print on the tick only; poll between ticks so a step that finishes
        # early is noticed immediately instead of after the sleep expires.
        if [ "$elapsed" -ge "$elapsed_at_tick" ]; then
            if [ -n "$N" ]; then
                printf "%s     still working... %dm%02ds elapsed" "$HB_CR" \
                    $(( elapsed / 60 )) $(( elapsed % 60 ))
            else
                printf "     still working... %dm%02ds elapsed\n" \
                    $(( elapsed / 60 )) $(( elapsed % 60 ))
            fi
            elapsed_at_tick=$(( elapsed + tick ))
        fi
        # Poll often enough that completion is prompt; the tick above controls
        # how often a line is actually printed.
        sleep 1
    done

    wait "$cmd_pid"
    rc=$?
    elapsed=$(( $(date +%s) - start ))
    printf "%s     finished in %dm%02ds\n" "$HB_CR" $(( elapsed / 60 )) $(( elapsed % 60 ))
    return "$rc"
}

# Download one URL with a byte/percent/rate meter, then verify the result is a
# gzip stream. curl is preferred because its progress meter reports an average
# rate; the Python fallback covers a Termux without curl. Both write to a .part
# file so a truncated transfer is never mistaken for a complete one.
download_with_progress() {
    local url="$1" dest="$2"
    local rc=0
    local part="${dest}.part"
    rm -f "$part"

    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 2 --retry-delay 2 --connect-timeout 15 \
            --speed-limit 1024 --speed-time 60 \
            -o "$part" "$url" 2>&1 | tee -a "$ERR_LOG"
        rc=${PIPESTATUS[0]}
    else
        python3 -c '
import os, sys, time, urllib.request
url, part = sys.argv[1], sys.argv[2]
clr = os.environ.get("DSH_CLR", "")
req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
try:
    with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as fh:
        total = int(resp.headers.get("content-length", 0))
        done, started = 0, time.time()
        while True:
            chunk = resp.read(131072)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            pct = int(done * 100 / total) if total else 0
            filled = int(pct * 24 / 100)
            bar = "#" * filled + "-" * (24 - filled)
            rate = done / 1048576 / max(0.1, time.time() - started)
            sys.stdout.write(
                f"\r  [{bar}] {pct:3d}%  {done / 1048576:.1f}/"
                f"{total / 1048576:.1f} MB  {rate:.2f} MB/s{clr}"
            )
            sys.stdout.flush()
        print()
except Exception as exc:
    print(f"\n  download failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
' "$url" "$part"
        rc=$?
    fi

    if [ "$rc" -ne 0 ] || [ ! -s "$part" ]; then
        rm -f "$part"
        return 1
    fi
    if ! gzip -t "$part" 2>/dev/null; then
        echo "  [!] $url did not deliver a valid gzip stream; discarding." >>"$ERR_LOG"
        rm -f "$part"
        return 1
    fi
    mv "$part" "$dest"
    return 0
}

fail_and_dump() {
    local step_name="$1"
    stop_spinner 1 "$step_name" 2>/dev/null || true
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${R}${W} INSTALLATION ERROR DIAGNOSTIC DUMP ${N}"
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}Stage Failed:${N} ${LG}${step_name}${N}\n"
    if [ -f "$ERR_LOG" ] && [ -s "$ERR_LOG" ]; then
        echo -e " ${G}Captured Diagnostic Output:${N}"
        sed 's/^/   /' "$ERR_LOG" | tail -n 25
    fi
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${W}Installation stopped. Run 'dsh-doctor' or check the diagnostics above.${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 1
}

banner() {
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}DEEPSEEK HARNESS${N} ${G}— Termux & Mobile Setup${N}"
    echo -e "${DG}${DIVIDER}${N}"
}

# ── Stage 1: Pre-flight Environment & External Asset Verification ─────────────
banner
printf " ${W}•${N} ${LG}Checking this device before installing...${N}\n"

ERRORS=()
REMEDIES=()
NOTICES=()

# 1. Termux OS Verification
if [ ! -d "/data/data/com.termux/files" ] && [ -z "${PREFIX:-}" ]; then
    ERRORS+=("Not running inside native Termux Android environment.")
    REMEDIES+=("Launch Termux on Android and run the installer from inside Termux.")
fi

# 2. Disk Storage Probe (Minimum 1,200 MB free)
FREE_KB=$(df -k "$HOME" 2>/dev/null | awk 'NR==2 {print $4}' || echo "")
case "$FREE_KB" in ''|*[!0-9]*) FREE_KB=0;; esac
FREE_MB=$(( FREE_KB / 1024 ))
if [ "$FREE_MB" -lt 1200 ]; then
    ERRORS+=("Insufficient disk space: only ${FREE_MB} MB free (1,200 MB required).")
    REMEDIES+=("Free disk storage by running 'pkg clean' and removing old caches/files.")
fi

# 3. CPU Architecture Probe
ARCH=$(uname -m 2>/dev/null || echo "unknown")
BIT=$(getconf LONG_BIT 2>/dev/null || echo "64")
if [ "$BIT" = "32" ] || [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armv8l" ] || [ "$ARCH" = "arm" ]; then
    NOTICES+=("32-bit CPU/userspace ($ARCH / ${BIT}-bit) detected; enabling pure-JS/WASM mode.")
fi

# 4. GitHub API Reachability
GH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 6 "https://api.github.com" 2>/dev/null || echo "")
case "$GH_CODE" in ''|*[!0-9]*) GH_CODE=000;; esac
if [ "$GH_CODE" = "000" ]; then
    ERRORS+=("GitHub API (api.github.com) is unreachable (connection timed out).")
    REMEDIES+=("Check your device's Wi-Fi/cellular connection, DNS, or VPN settings.")
fi

# 5. Git Remote Repository Reachability
REPO_OWNER="${DSH_REPO_OWNER:-salmanbappi}"
REPO_NAME="${DSH_REPO_NAME:-deepseek-harness}"
REPO_URL="https://github.com/$REPO_OWNER/$REPO_NAME.git"
REPO_CODE=$(curl -sIL -o /dev/null -w "%{http_code}" --connect-timeout 6 "$REPO_URL" 2>/dev/null || echo "")
case "$REPO_CODE" in ''|*[!0-9]*) REPO_CODE=000;; esac
if [ "$REPO_CODE" = "000" ] || [ "$REPO_CODE" -ge 400 ]; then
    ERRORS+=("Git repository is unreachable at $REPO_URL (HTTP $REPO_CODE).")
    REMEDIES+=("Ensure GitHub is accessible without local proxy or firewall blocking.")
fi

# 6. Latest Release Prebuilt Tarball Probe
LATEST_TAG=$(curl -sI --connect-timeout 6 "https://github.com/$REPO_OWNER/$REPO_NAME/releases/latest" 2>/dev/null | grep -i "^location:" | awk '{print $2}' | tr -d '\r\n' | sed -E 's|.*/tag/||' || true)

if [ -z "$LATEST_TAG" ]; then
    LATEST_JSON=$(curl -sL --connect-timeout 6 "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest" 2>/dev/null || true)
    LATEST_TAG=$(echo "$LATEST_JSON" | grep '"tag_name":' | head -n 1 | cut -d '"' -f 4 || true)
fi

if [ -n "$LATEST_TAG" ]; then
    TARBALL_URL="https://github.com/$REPO_OWNER/$REPO_NAME/releases/download/$LATEST_TAG/dsh-termux-prebuilt-${LATEST_TAG}.tar.gz"
    TAR_CODE=$(curl -sIL -o /dev/null -w "%{http_code}" --connect-timeout 6 "$TARBALL_URL" 2>/dev/null || echo "")
    case "$TAR_CODE" in ''|*[!0-9]*) TAR_CODE=000;; esac
    if [ "$TAR_CODE" != "200" ] && [ "$TAR_CODE" != "302" ]; then
        NOTICES+=("Release $LATEST_TAG tarball returned HTTP $TAR_CODE; local fallback will engage.")
    fi
else
    NOTICES+=("Could not query GitHub releases API; repository git sync will proceed directly.")
fi

# Pre-flight Abort Gate
if [ "${#ERRORS[@]}" -gt 0 ]; then
    printf "\r ${R}${W} ✕${N} %s ${R}${W}FAILED${N}\n" "Pre-flight checks"
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${R}${W} SETUP STOPPED ${N}"
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}Found ${#ERRORS[@]} problem(s) that must be fixed first:${N}\n"
    for i in "${!ERRORS[@]}"; do
        idx=$(( i + 1 ))
        echo -e "  ${W}${idx}.${N}  ${LG}${ERRORS[$i]}${N}"
        echo -e "       ${G}Remedy:${N}  ${G}${REMEDIES[$i]}${N}\n"
    done
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}No files or repositories were modified. Setup aborted safely.${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 1
fi

printf " ${W}●${N} %s\n" "Pre-flight checks passed"
for notice in "${NOTICES[@]}"; do
    echo -e "   ${DG}↳ ${G}${notice}${N}"
done

# ── Stage 2: Minimal System Toolchain Check & Installation ─────────────────────
start_spinner "Installing the tools dsh needs (Node, Python, Git)..."
PACKAGES="nodejs-lts python git tar curl"
MISSING_PKGS=""
for pkg in $PACKAGES; do
    if ! command -v "$pkg" &>/dev/null && ! dpkg -s "$pkg" &>/dev/null; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [ -n "$MISSING_PKGS" ]; then
    pkg update -y >"$ERR_LOG" 2>&1 || true
    pkg install -y -o Dpkg::Options::="--force-confold" $MISSING_PKGS >"$ERR_LOG" 2>&1 || \
        apt-get install -y $MISSING_PKGS >"$ERR_LOG" 2>&1 || fail_and_dump "System packages ($MISSING_PKGS)"
    pkg clean 2>/dev/null || true
fi

# Ensure pnpm is available (Termux pkg or npm fallback, never @pnpm/exe)
if ! command -v pnpm &>/dev/null; then
    apt-get install --reinstall -y pnpm >"$ERR_LOG" 2>&1 || \
        pkg install -y -o Dpkg::Options::="--force-confold" pnpm >"$ERR_LOG" 2>&1 || \
        npm install -g pnpm@9 >"$ERR_LOG" 2>&1 || \
        npm install -g pnpm >"$ERR_LOG" 2>&1 || true
    hash -r 2>/dev/null || true
fi

if ! command -v pnpm &>/dev/null; then
    echo "pnpm command not found after installation attempt" >"$ERR_LOG"
    fail_and_dump "Package Manager Setup (pnpm)"
fi
stop_spinner 0 "Tools installed"

# ── Stage 3: DeepSeek Harness Repository Workspace Sync ────────────────────────
DSH_DIR="$HOME/deepseek-harness"
REPO_HTTPS="https://github.com/$REPO_OWNER/$REPO_NAME.git"
REPO_SLUG="$REPO_OWNER/$REPO_NAME"
start_spinner "Getting the dsh source code..."
git config --global --add safe.directory "$DSH_DIR" 2>/dev/null || true

# A checkout left by another installer still has that installer's `origin`, and
# the update path below would then fetch from it. The banner would still say
# this repo's name, so the mismatch has to be checked, not assumed.
NEED_CLONE=0
if [ -d "$DSH_DIR/.git" ]; then
    # Distinguish "this checkout has no origin" from "git could not answer".
    # Both look like an empty string, but only the first justifies deleting the
    # directory: a transient git failure would otherwise wipe a healthy tree,
    # and the re-clone that follows fails under the same conditions that broke
    # the probe, leaving the user with nothing.
    if EXISTING_ORIGIN=$(git -C "$DSH_DIR" remote get-url origin 2>/dev/null); then
        case "$EXISTING_ORIGIN" in
            *"$REPO_SLUG"*) ;;
            *)
                echo "  [!] $DSH_DIR tracks '${EXISTING_ORIGIN:-no origin}', not $REPO_SLUG; re-cloning." >>"$ERR_LOG"
                NEED_CLONE=1
                ;;
        esac
    else
        # `git remote get-url` exits 2 when the remote is simply absent, and
        # something else when git itself fails. Treat a checkout that has a HEAD
        # as usable and let the update path report any real problem.
        if git -C "$DSH_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
            echo "  [i] Could not read $DSH_DIR's origin; keeping the existing checkout." >>"$ERR_LOG"
        else
            NEED_CLONE=1
        fi
    fi
    # A missing or unreadable HEAD means an interrupted clone, which `git pull`
    # would report as a confusing error instead of the real cause.
    if [ "$NEED_CLONE" -eq 0 ] && ! git -C "$DSH_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
        echo "  [!] $DSH_DIR has no usable commit (interrupted clone?); re-cloning." >>"$ERR_LOG"
        NEED_CLONE=1
    fi
elif [ -e "$DSH_DIR" ]; then
    echo "  [!] $DSH_DIR exists but is not a git checkout; replacing it." >>"$ERR_LOG"
    NEED_CLONE=1
else
    # Nothing there at all — the common first install. Without this branch
    # NEED_CLONE stays 0 and the update path runs `cd` into a directory that
    # does not exist yet.
    NEED_CLONE=1
fi

if [ "$NEED_CLONE" -eq 1 ]; then
    # The clone writes through a staging path so its own retries never land on
    # top of a half-written previous attempt.
    rm -rf "$DSH_DIR"
fi

# Credentials are never collected here: this install is non-interactive, and a
# prompt would block forever behind the spinner instead of failing.
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS=/bin/true
export GIT_HTTP_LOW_SPEED_LIMIT=1000
export GIT_HTTP_LOW_SPEED_TIME=60

if [ "$NEED_CLONE" -eq 0 ]; then
    cd "$DSH_DIR" || fail_and_dump "Workspace Change Directory"
    stop_spinner 0 "Using the source you already have"
    run_with_progress "Downloading the latest dsh source" \
        git -C "$DSH_DIR" -c advice.detachedHead=false fetch origin master --progress || \
        fail_and_dump "Repository Fetch (git fetch)"
    run_with_progress "Switching to the master branch" \
        git -C "$DSH_DIR" -c advice.detachedHead=false checkout master || \
        fail_and_dump "Repository Checkout (git checkout)"
    # The previous run's patcher left tracked files modified — package.json, the
    # cordis overlays, patches/*.patch and patch_termux.py itself — and a
    # fast-forward refuses to overwrite them, so an upgrade over an existing
    # prior install aborts here every time. That output is regenerated from the
    # source by the patcher later in this install, so discard it rather than
    # stash: a stash would also preserve a stale patch bundle over the new one.
    if ! git -C "$DSH_DIR" diff --quiet || ! git -C "$DSH_DIR" diff --cached --quiet; then
        echo "  [i] Discarding the previous run's generated changes before updating." >>"$ERR_LOG"
        git -C "$DSH_DIR" checkout -- . >>"$ERR_LOG" 2>&1 || \
            fail_and_dump "Repository Update (a modified tracked file could not be reset; move it aside by hand and re-run)"
    fi
    run_with_progress "Applying the latest changes" \
        git -C "$DSH_DIR" -c advice.detachedHead=false pull --ff-only origin master --progress || \
        fail_and_dump "Repository Update (git pull)"
else
    MAX_RETRIES=3
    COUNT=0
    CLONED=0
    while [ "$COUNT" -lt "$MAX_RETRIES" ]; do
        COUNT=$((COUNT+1))
        ATTEMPT_DIR="${DSH_DIR}.clone.$$"
        rm -rf "$ATTEMPT_DIR"
        stop_spinner 0 "Downloaded the source (attempt $COUNT of $MAX_RETRIES)"
        if run_with_progress "Downloading the dsh source" \
            git clone --depth=1 --progress "$REPO_HTTPS" "$ATTEMPT_DIR"; then
            rm -rf "$DSH_DIR"
            mv "$ATTEMPT_DIR" "$DSH_DIR" || fail_and_dump "Repository Clone (finalize)"
            CLONED=1
            break
        fi
        rm -rf "$ATTEMPT_DIR"
        if [ "$COUNT" -lt "$MAX_RETRIES" ]; then
            echo -e " ${Y}↳${N} clone failed; retrying in $((COUNT * 5))s"
            sleep $((COUNT * 5))
        fi
        start_spinner "Download failed; retrying..."
    done
    if [ "$CLONED" -eq 0 ]; then
        fail_and_dump "Repository Clone (git clone)"
    fi
    cd "$DSH_DIR" || fail_and_dump "Workspace Change Directory"
fi
stop_spinner 0 "Source code ready"

# ── Stage 4: Deploy Pre-compiled Cloud Release Artifacts ──────────────────────
start_spinner "Looking up the newest dsh build..."
cd "$DSH_DIR" || fail_and_dump "Workspace Change Directory"
DOWNLOAD_SUCCESS=0

# A previously unpacked build is only reusable if it is the release we would
# otherwise download. Checking for files alone reports "Verified" over an older
# bundle, which is how an install silently stays on the previous release.
INSTALLED_TAG=""
if [ -f ".dsh-prebuilt-tag" ]; then
    INSTALLED_TAG=$(cat ".dsh-prebuilt-tag" 2>/dev/null || true)
fi
if [ -f "apps/cli/lib/bin.js" ] && [ -d "apps/web/dist" ] && [ -f "packages/client/ui-chat/lib/client.js" ] \
    && { [ -z "$LATEST_TAG" ] || [ "$INSTALLED_TAG" = "$LATEST_TAG" ]; }; then
    DOWNLOAD_SUCCESS=1
    # An unreadable release list reuses the existing build; name the tag as
    # unknown rather than printing a bare "Verified".
    stop_spinner 0 "Already on ${INSTALLED_TAG:-the newest build (release list unreadable)}"
else
    if [ -n "$LATEST_TAG" ]; then
        stop_spinner 0 "Installing build $LATEST_TAG"
        TARBALL_URL="https://github.com/$REPO_OWNER/$REPO_NAME/releases/download/$LATEST_TAG/dsh-termux-prebuilt-${LATEST_TAG}.tar.gz"
        DEST_TAR="$DSH_DIR/prebuilt.tar.gz"

        echo -e " ${DG}↳${N} release ${G}${LATEST_TAG}${N} — $(curl -sIL --connect-timeout 6 "$TARBALL_URL" 2>/dev/null | awk 'tolower($1)=="content-length:"{v=$2} END{if (v!="") printf "%.1f MB\n", v/1048576; else print "size unknown"}')"
        if download_with_progress "$TARBALL_URL" "$DEST_TAR"; then
            ARCHIVE_OK=1
        else
            ARCHIVE_OK=0
            echo "  [!] Could not download a usable bundle from $TARBALL_URL." >>"$ERR_LOG"
        fi

        if [ "$ARCHIVE_OK" -eq 1 ]; then
            # Extract to a staging directory first, so a partial unpack cannot
            # leave the checkout half-replaced.
            EXTRACT_DIR=$(mktemp -d "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/dsh_prebuilt_XXXXXX")
            EXTRACTED=0
            if tar -xzf "$DEST_TAR" -C "$EXTRACT_DIR" >"$ERR_LOG" 2>&1 \
                && [ -f "$EXTRACT_DIR/apps/cli/lib/bin.js" ]; then
                cp -R "$EXTRACT_DIR"/. "$DSH_DIR"/ 2>>"$ERR_LOG"
                EXTRACTED=1
            else
                echo "  [!] $LATEST_TAG did not unpack into a usable tree." >>"$ERR_LOG"
            fi
            rm -rf "$EXTRACT_DIR"
            rm -f "$DEST_TAR"
            # The stamp records what was installed, so it may only be written
            # when this archive actually produced the tree. Writing it on a
            # failed unpack makes the next run see a matching tag over an old
            # build and skip the download forever.
            if [ "$EXTRACTED" -eq 1 ]; then
                DOWNLOAD_SUCCESS=1
                printf '%s\n' "$LATEST_TAG" >.dsh-prebuilt-tag
            fi
        fi
        rm -f "$DEST_TAR"
    fi

    if [ "$DOWNLOAD_SUCCESS" -eq 0 ]; then
        # Compiling needs the workspace dependencies, which stage 5 installs
        # later. Install them first or the three build commands below cannot
        # run at all — `tsx` and the rest are devDependencies.
        start_spinner "No prebuilt build available; installing dependencies to compile locally..."
        # `>>` not `>`: fail_and_dump prints $ERR_LOG, and truncating it at each
        # step leaves it holding only the last command's output, so the run that
        # actually failed reports nothing.
        COREPACK_ENABLE_PROJECT_SPEC=0 COREPACK_ENABLE_STRICT=0 \
            pnpm install --frozen-lockfile=false --ignore-scripts >>"$ERR_LOG" 2>&1
        INSTALL_RC=$?
        stop_spinner 0 "Dependencies installed"
        start_spinner "Compiling dsh on this device (this takes a while)..."
        pnpm run build:lib:host >>"$ERR_LOG" 2>&1; HOST_RC=$?
        pnpm run build:lib:client >>"$ERR_LOG" 2>&1; CLIENT_RC=$?
        pnpm run build:web >>"$ERR_LOG" 2>&1; WEB_RC=$?
        stop_spinner 0 "Compiled on this device"
        # `bin.js` existing is not proof the build succeeded: host can emit it
        # while the client or web build fails, which ships a tree whose UI is
        # stale or absent. Report which step failed rather than a success banner.
        if [ "$INSTALL_RC" -ne 0 ] || [ "$HOST_RC" -ne 0 ] || [ "$CLIENT_RC" -ne 0 ] || [ "$WEB_RC" -ne 0 ]; then
            echo "   [!] Local compile reported failures: install=$INSTALL_RC host=$HOST_RC client=$CLIENT_RC web=$WEB_RC" >&2
            fail_and_dump "Deploy Build Artifacts (the local compile failed: install=$INSTALL_RC host=$HOST_RC client=$CLIENT_RC web=$WEB_RC)"
        fi
        if [ ! -f "apps/cli/lib/bin.js" ]; then
            fail_and_dump "Deploy Build Artifacts (no prebuilt bundle and the local compile produced apps/cli/lib/bin.js)"
        fi
    fi
fi

# ── Stage 5: Termux Mobile UX Suite & Dependency Linking ──────────────────────
start_spinner "Applying the Android fixes and linking dependencies..."
cd "$DSH_DIR" || fail_and_dump "Workspace Change Directory"

# Global CLI launcher commands (~/bin)
BIN_DIR="$HOME/bin"
mkdir -p "$BIN_DIR"

cat <<'LAUNCHER_EOF' > "$BIN_DIR/dsh"
#!/data/data/com.termux/files/usr/bin/bash
set -e
# pnpm publishes no android-arm binary at any version, and no android-* binary
# before 12.18. The repository pins packageManager to a release from before
# that, so without these two settings every pnpm call dsh makes at startup
# tries to fetch an uncompilable @pnpm/exe and fails. The Termux-packaged pnpm
# is a native binary and is the supported one here.
export COREPACK_ENABLE_PROJECT_SPEC=0
export COREPACK_ENABLE_STRICT=0
export COREPACK_ENABLE_AUTO_PIN=0
export pnpm_config_pm_on_fail=ignore
export pnpm_config_manage_package_manager_versions=false
# Size the heap to the device rather than to a desktop default. 2560 MB exceeds
# the free memory on a 2 GB phone, where V8 will grow toward the ceiling and can
# take the whole device down before it collects. Override with DSH_MAX_OLD_SPACE.
_dsh_total_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null)
case "$_dsh_total_mb" in ''|*[!0-9]*) _dsh_total_mb=2048;; esac
if [ "$_dsh_total_mb" -ge 3500 ]; then _dsh_space=1536
elif [ "$_dsh_total_mb" -ge 2500 ]; then _dsh_space=1024
else _dsh_space=768
fi
export NODE_OPTIONS="--max-old-space-size=${DSH_MAX_OLD_SPACE:-$_dsh_space} ${NODE_OPTIONS:-}"
unset _dsh_total_mb _dsh_space
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

if [ -f "$DSH_DIR/scripts/dsh-update.sh" ]; then
    cp -f "$DSH_DIR/scripts/dsh-update.sh" "$BIN_DIR/dsh-update"
fi
chmod +x "$BIN_DIR/dsh-update" 2>/dev/null || true

cat <<'DOCTOR_EOF' > "$BIN_DIR/dsh-doctor"
#!/data/data/com.termux/files/usr/bin/bash
set -e
DSH_DIR="$HOME/deepseek-harness"
echo "──────────────────────────────────────────"
echo "      DeepSeek Harness Termux Doctor      "
echo "──────────────────────────────────────────"
echo "[*] Node.js:           $(node -v 2>/dev/null || echo 'FAIL')"
echo "[*] pnpm:              $(pnpm -v 2>/dev/null || echo 'FAIL')"
echo "[*] Python3:           $(python3 --version 2>/dev/null || echo 'FAIL')"
echo "[*] Workspace:         $DSH_DIR"
if [ -d "$DSH_DIR" ]; then
    cd "$DSH_DIR"
    python3 scripts/patch_termux.py --check || true
    echo ""
    echo "[*] Native Addons & Plugins:"
    node -e "try { require('sharp'); console.log('    - sharp (raster images):   OK'); } catch(e) { console.log('    - sharp: FAIL (' + e.message + ')'); }" 2>/dev/null || true
    node -e "try { require('node-pty'); console.log('    - node-pty (terminal):     OK'); } catch(e) { console.log('    - node-pty: FAIL (' + e.message + ')'); }" 2>/dev/null || true
    echo ""
    echo "[*] CLI Invocation Check:"
    if dsh --version >/dev/null 2>&1; then
        echo "    SUCCESS -> Version $(dsh --version 2>/dev/null)"
    else
        echo "    FAILED -> dsh failed to start"
    fi
fi
echo "──────────────────────────────────────────"
DOCTOR_EOF
chmod +x "$BIN_DIR/dsh-doctor"

cat <<'PATCH_EOF' > "$BIN_DIR/dsh-patch"
#!/data/data/com.termux/files/usr/bin/bash
set -e
DSH_DIR="$HOME/deepseek-harness"
if [ ! -d "$DSH_DIR" ]; then
    echo "[!] Error: Harness directory not found at $DSH_DIR" >&2
    exit 1
fi
cd "$DSH_DIR" || fail_and_dump "Workspace Change Directory"
python3 "$DSH_DIR/scripts/patch_termux.py" "$@"
PATCH_EOF
chmod +x "$BIN_DIR/dsh-patch"

# Put ~/bin on PATH in the shell rc files the user already has. Creating the
# others would leave a .zshrc or .bash_profile behind for a shell they may never
# run, and the installer has no removal path for them. The marker is matched
# anchored so an unrelated mention of $HOME/bin does not suppress the line.
for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.bash_profile"; do
    if [ -f "$rc" ]; then
        if ! grep -qE '^[[:space:]]*export[[:space:]]+PATH=.*\$HOME/bin' "$rc"; then
            printf '\n# Added by the dsh Termux installer\nexport PATH="$HOME/bin:$PATH"\n' >> "$rc"
        fi
    fi
done
command -v bash >/dev/null 2>&1 && [ ! -f "$HOME/.bashrc" ] && \
    echo "   note: ~/bin is on PATH for this run only; add it to your shell rc to keep it."
export PATH="$HOME/bin:$PATH"

# Apply mobile patches
python3 scripts/patch_termux.py --apply >"$ERR_LOG" 2>&1 || true

# Production-only dependency install saves 2-3 GB of devDependencies. The lock
# is not frozen: this tree was just patched, so the patched manifests are what
# must be resolved. Kept in the same process env because both the pnpm and the
# npm fallback need Corepack's native-binary workaround.
export COREPACK_ENABLE_PROJECT_SPEC=0 COREPACK_ENABLE_STRICT=0 CI=true

INSTALL_OK=0
if command -v pnpm >/dev/null 2>&1; then
    # 40 minutes: a cold cache over mobile data legitimately takes this long,
    # and the heartbeat keeps it distinguishable from a stall until then.
    if run_install_step "Installing dependencies with pnpm (production only)" 2400 \
        pnpm install --prod --frozen-lockfile=false --ignore-scripts; then
        INSTALL_OK=1
    else
        echo "   pnpm install did not finish; trying npm instead"
    fi
fi

if [ "$INSTALL_OK" -eq 0 ]; then
    if run_install_step "Installing dependencies with npm (production only)" 2400 \
        npm install --omit=dev --ignore-scripts; then
        INSTALL_OK=1
    fi
fi

if [ "$INSTALL_OK" -eq 0 ]; then
    fail_and_dump "Install Production Dependencies (neither pnpm nor npm completed)"
fi

# sharp has no android-arm build; the wasm build is the one that works. A
# failure here is not fatal — image handling degrades, the harness still runs —
# so say so rather than claiming the step succeeded.
if ! run_install_step "Adding the wasm image build of sharp" 600 \
    pnpm add -w @img/sharp-wasm32 --ignore-scripts; then
    echo "   [!] sharp/wasm not installed; image features may be unavailable."
fi

# LibreOffice WASM: the kit's wasm variant declares no os/cpu constraint, so pnpm
# installs it here — measured at ~152 MB, for a document converter the phone
# profile has disabled. Removing it after install is what reclaims the space; the
# overlay gate only stops the plugin loading. A missing module degrades to
# "office conversion unavailable", which is the intended state on a phone.
# `-name` matches a basename and never crosses `/`, so the pattern is bare, and
# the real package sits at node_modules/.pnpm/<name>@<ver>/node_modules/<name>
# — depth 5, past the 4 the first attempt used, which silently matched nothing
# while still printing the line below. Both -type d (the pnpm store copy) and
# -type l (workspace symlink) are matched, since removing only the former
# leaves a dangling symlink behind.
LO_REMOVED=$(find "$DSH_DIR/node_modules" -maxdepth 6 \( -type d -o -type l \) \
    -name 'libreoffice-kit-*' -prune -print0 2>/dev/null | xargs -0 -r rm -rfv 2>/dev/null | wc -l)
if [ "$LO_REMOVED" -gt 0 ]; then
    echo "   removed the LibreOffice WASM payload (not usable on Android)"
else
    echo "   [!] LibreOffice WASM payload not found to remove (expected on a partial install)"
fi

# Prune unneeded package caches
pnpm store prune 2>/dev/null || true
pkg clean 2>/dev/null || true

python3 scripts/patch_termux.py --apply >"$ERR_LOG" 2>&1 || fail_and_dump "Termux Mobile Environment Suite"

stop_spinner 0 "Android fixes applied"

# ── Setup Complete Banner ─────────────────────────────────────────────────────
echo -e "${DG}${DIVIDER}${N}"
echo -e " ${W}DEEPSEEK HARNESS — SETUP COMPLETE${N}"
echo -e "${DG}${DIVIDER}${N}"
echo -e " ${W}[✓] DeepSeek Harness successfully installed on Termux!${N}\n"
echo -e " ${W}Commands Available:${N}"
echo -e "   ${W}dsh web${N}        ${G}Start the Mobile Web UI (http://127.0.0.1:3080)${N}"
echo -e "   ${W}dsh-update${N}     ${G}Zero-loss upstream updater${N}"
echo -e "   ${W}dsh-doctor${N}     ${G}Verify environment & patch integrity${N}\n"
echo -e " ${W}To start right now:${N}"
echo -e "   ${W}dsh web${N}"
echo -e "${DG}${DIVIDER}${N}\n"
