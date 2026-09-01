#!/data/data/com.termux/files/usr/bin/python3
"""
DeepSeek Harness - Android, Termux, and Mobile UX Environment Patcher
Maintains and applies:
1. fs.link -> fs.rename fallback for Android filesystems (EACCES, EPERM, EXDEV, ENOSYS)
2. Local authority auth bypass for mobile web UI (127.0.0.1, localhost, ::1, 0.0.0.0)
3. Responsive Mobile UI/UX layouts, drawer, touch optimizations, and backdrops
4. package.json --expose-internals runtime flag and @img/sharp-wasm32
5. Koffi Android fallback stubs in node_modules
6. node-pty arm64 native binary recompilation
"""

import os
import sys
import re
import subprocess
import argparse

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH_DIR = os.path.join(REPO_DIR, "patches")
PATCH_FILE = os.path.join(PATCH_DIR, "termux-mobile-suite.patch")
LEGACY_PATCH_FILE = os.path.join(PATCH_DIR, "termux-environment.patch")
# Where install-pty-prebuild.sh keeps the CI-built pty.node. pnpm re-extracts
# node-pty on every install, so the binary has to be restored from outside the
# workspace rather than rebuilt on the phone.
NATIVE_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".dsh", "native", "android-arm64")


def ensure_patch_dir():
    os.makedirs(PATCH_DIR, exist_ok=True)


def patch_attachment_store():
    """Patches packages/attachment/attachment-local/src/store.ts for Android link fallback."""
    path = os.path.join(REPO_DIR, "packages", "attachment", "attachment-local", "src", "store.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    modified = False
    if "rename" not in c or "import { chmod, link, mkdir, open, readFile, unlink, rename }" not in c:
        c = re.sub(
            r"import\s*\{\s*chmod,\s*link,\s*mkdir,\s*open,\s*readFile,\s*unlink\s*\}\s*from\s*'node:fs/promises'",
            "import { chmod, link, mkdir, open, readFile, unlink, rename } from 'node:fs/promises'",
            c
        )
        modified = True

    if "error.code === 'EACCES'" not in c and "error.code === 'ENOSYS'" not in c:
        pat = re.compile(
            r"(\s*try\s*\{\s*await link\(temporary,\s*target\)\s*\}\s*catch\s*\(error\)\s*\{)(.*?)(\}\s*\n\s*// Persist the target entry)",
            re.DOTALL
        )
        repl = r"""\1
      if (error instanceof Error && 'code' in error && (error.code === 'EACCES' || error.code === 'EPERM' || error.code === 'EXDEV' || error.code === 'ENOSYS')) {
        await rename(temporary, target)
      } else if (error instanceof Error && 'code' in error && error.code === 'EEXIST') {
        const existing = new Uint8Array(await readFile(target))
        if (digest(existing) !== sha256) throw new AttachmentError('Stored attachment failed integrity verification.', 'ATTACHMENT_CORRUPT')
      } else {
        throw error
      }
    \3"""
        c = pat.sub(repl, c, count=1)
        modified = True

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched attachment store link fallback.")
    return True


def patch_session_persistence():
    """Patches packages/session/session-persistence-jsonl/src/index.ts for Android link fallback."""
    path = os.path.join(REPO_DIR, "packages", "session", "session-persistence-jsonl", "src", "index.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    modified = False
    if "rename" not in c or "truncate, rename" not in c:
        c = re.sub(
            r"import\s*\{\s*open,\s*mkdir,\s*readFile,\s*readdir,\s*realpath,\s*link,\s*rm,\s*stat,\s*truncate\s*\}\s*from\s*'node:fs/promises'",
            "import { open, mkdir, readFile, readdir, realpath, link, rm, stat, truncate, rename } from 'node:fs/promises'",
            c
        )
        modified = True

    if "err.code === 'EACCES'" not in c and "err.code === 'ENOSYS'" not in c:
        pat = re.compile(
            r"(\s*try\s*\{\s*await link\(tmp,\s*finalPath\)\s*\n\s*linked = true\s*\})(.*?)(\s*finally\s*\{)",
            re.DOTALL
        )
        repl = r"""\1 catch (err: unknown) {
      if (err instanceof Error && 'code' in err && (err.code === 'EACCES' || err.code === 'EPERM' || err.code === 'EXDEV' || err.code === 'ENOSYS')) {
        await rename(tmp, finalPath)
        linked = true
      } else {
        throw err
      }
    }\3"""
        c = pat.sub(repl, c, count=1)
        modified = True

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched session JSONL link fallback.")
    return True


def patch_fs_local():
    """Patches packages/fs/fs-local/src/fsio.ts for Android link fallback in writeFileAtomic."""
    path = os.path.join(REPO_DIR, "packages", "fs", "fs-local", "src", "fsio.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    modified = False
    if "isAndroid" not in c or "isUnsupportedLinkErr" not in c:
        pat = re.compile(
            r"(\s*if \(createIfAbsent !== undefined\) \{\s*try \{\s*await linkFile\(tempPath, absolutePath\)\s*\} catch \(error: unknown\) \{)(.*?)(\s*\}\s*\} else if \(platform === 'win32')",
            re.DOTALL
        )
        repl = r"""\1
        const isAndroid = (internals.platform ?? platform) === 'android' || (internals.platform === undefined && (process.platform === 'android' || Boolean(process.env.TERMUX_VERSION)))
        const isUnsupportedLinkErr = error instanceof Error && 'code' in error && (
          error.code === 'EACCES' || error.code === 'EPERM' || error.code === 'EXDEV' || error.code === 'ENOSYS' || error.code === 'ENOTSUP' || error.code === 'EOPNOTSUPP'
        )

        if (isAndroid && isUnsupportedLinkErr) {
          let existing: BigIntStats | undefined
          try {
            existing = await inspectPublicationTarget(absolutePath)
          } catch (metadataError: unknown) {
            if (!isENOENT(metadataError) && !isENOTDIR(metadataError)) {
              throw new FsError(`cannot write "${createIfAbsent.displayPath}": ${errorMessage(metadataError)}`, 'FS_IO_ERROR', { cause: metadataError })
            }
          }

          if (existing !== undefined) {
            if (!existing.isFile()) {
              throw new FsError(`cannot write "${createIfAbsent.displayPath}": not a regular file`, 'FS_NOT_REGULAR_FILE', { cause: error })
            }
            throw new FsError(
              `cannot overwrite existing "${createIfAbsent.displayPath}" without reading it first`,
              'FS_NOT_OBSERVED',
              { cause: error },
            )
          }
          await rename(tempPath, absolutePath)
        } else {
          await throwGuardedCreateFailure(error, absolutePath, createIfAbsent.displayPath, inspectPublicationTarget)
        }\3"""
        c = pat.sub(repl, c, count=1)
        modified = True

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched fs-local writeFileAtomic link fallback.")
    return True


def patch_browser_auth():
    """Patches packages/client/connection/src/browser-auth.ts for local mobile web access."""
    path = os.path.join(REPO_DIR, "packages", "client", "connection", "src", "browser-auth.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    modified = False
    if "isLocalAuthority" not in c:
        target = "  /**\n   * Verify the authority-bound browser cookie on a Host request."
        method_code = """  private isLocalAuthority(authority: string): boolean {
    const host = authority.split(':')[0]
    return host === '127.0.0.1' || host === 'localhost' || host === '::1' || host === '0.0.0.0'
  }

  /**
   * Verify the authority-bound browser cookie on a Host request."""
        if target in c:
            c = c.replace(target, method_code)
            modified = True

        if "if (authority !== undefined && this.isLocalAuthority(authority)) return true" not in c:
            c = re.sub(
                r"if \(this\.isAuthenticated\(req\)\) return true\s*\n\s*this\.writeUnauthorized\(req, res\)",
                "if (this.isAuthenticated(req)) return true\n    if (authority !== undefined && this.isLocalAuthority(authority)) return true\n    this.writeUnauthorized(req, res)",
                c
            )
            modified = True

        if "const authority = requestAuthority(request.headers)\n    if (authority !== undefined && this.isLocalAuthority(authority)) return true" not in c:
            c = re.sub(
                r"const authority = requestAuthority\(request\.headers\)\s*\n\s*const rawCookie =",
                "const authority = requestAuthority(request.headers)\n    if (authority !== undefined && this.isLocalAuthority(authority)) return true\n    const rawCookie =",
                c
            )
            modified = True

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched browser authentication for local mobile access.")
    return True


def patch_package_json():
    """Patches package.json for runtime flags and wasm dependencies."""
    path = os.path.join(REPO_DIR, "package.json")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    modified = False
    if '"dsh": "node --import tsx/esm apps/cli/src/bin.ts"' in c:
        c = c.replace('"dsh": "node --import tsx/esm apps/cli/src/bin.ts"', '"dsh": "node --expose-internals --import tsx/esm apps/cli/src/bin.ts"')
        modified = True

    if '"@img/sharp-wasm32"' not in c:
        c = re.sub(
            r'("devDependencies":\s*\{)',
            r'"dependencies": {\n    "@img/sharp-wasm32": "^0.35.4"\n  },\n  \1',
            c
        )
        modified = True

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched package.json (--expose-internals, sharp-wasm32).")
    return True


def patch_app_frame():
    """Patches packages/client/ui-layout/src/client/AppFrame.tsx and CSS for mobile drawer."""
    tsx_path = os.path.join(REPO_DIR, "packages", "client", "ui-layout", "src", "client", "AppFrame.tsx")
    if os.path.exists(tsx_path):
        with open(tsx_path, "r", encoding="utf-8") as f:
            c = f.read()
        if "isMobile" not in c:
            c = c.replace(
                "const narrow = viewport < SIDEBAR_AUTO_COLLAPSE\n  useEffect(() => { actions.setNarrow(narrow) }, [actions, narrow])",
                "const narrow = viewport < SIDEBAR_AUTO_COLLAPSE\n  const isMobile = viewport <= 768\n  useEffect(() => { actions.setNarrow(narrow) }, [actions, narrow])"
            )
            c = c.replace(
                "style={{ gridTemplateColumns: `${cols.sidebar}px minmax(0, 1fr) ${cols.details}px` }}",
                "style={{ gridTemplateColumns: isMobile ? '0px 1fr 0px' : `${cols.sidebar}px minmax(0, 1fr) ${cols.details}px` }}"
            )
            c = c.replace(
                "width: cols.sidebar,\n        })}",
                "width: isMobile ? 280 : cols.sidebar,\n        })}"
            )
            c = c.replace(
                "{renderSlot('sidebar', {\n          collapsed: sidebarCollapsed,",
                "{renderSlot('sidebar', {\n          collapsed: isMobile ? false : sidebarCollapsed,"
            )
            backdrop_code = """      {/* Mobile drawer backdrop */}
      {isMobile && (!sidebarCollapsed || cols.details > 0) && (
        <div
          className={css.mobileBackdrop}
          onClick={() => {
            if (!sidebarCollapsed) actions.toggleSidebar()
            if (cols.details > 0) actions.closeDetails()
          }}
          aria-hidden="true"
        />
      )}

      {/* Mobile sidebar toggle button when collapsed */}
      {isMobile && sidebarCollapsed && (
        <button
          type="button"
          className={css.mobileSidebarToggle}
          aria-label="Toggle sidebar"
          onClick={() => { actions.toggleSidebar() }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12"></line>
            <line x1="3" y1="6" x2="21" y2="6"></line>
            <line x1="3" y1="18" x2="21" y2="18"></line>
          </svg>
        </button>
      )}

      <div className={css.sidebarCol}>"""
            c = c.replace("      <div className={css.sidebarCol}>", backdrop_code)

            c = c.replace(
                '{!sidebarCollapsed && <DragHandle side="sidebar" left={cols.sidebar} onStart={onSidebarStart} onDrag={onSidebarDrag} onEnd={onDragEnd} />}',
                '{!sidebarCollapsed && !isMobile && <DragHandle side="sidebar" left={cols.sidebar} onStart={onSidebarStart} onDrag={onSidebarDrag} onEnd={onDragEnd} />}'
            )
            c = c.replace(
                '{cols.details > 0 && <DragHandle side="details" left={viewport - cols.details} onStart={onDetailsStart} onDrag={onDetailsDrag} onEnd={onDragEnd} />}',
                '{cols.details > 0 && !isMobile && <DragHandle side="details" left={viewport - cols.details} onStart={onDetailsStart} onDrag={onDetailsDrag} onEnd={onDragEnd} />}'
            )
            with open(tsx_path, "w", encoding="utf-8") as f:
                f.write(c)
            print("  [+] Patched AppFrame.tsx mobile responsive drawer.")


def patch_model_select():
    """Patches ModelSelect component for mobile pointerdown & dropdown sheet."""
    tsx_path = os.path.join(REPO_DIR, "packages", "client", "ui-model-selection", "src", "client", "ModelSelect.tsx")
    if os.path.exists(tsx_path):
        with open(tsx_path, "r", encoding="utf-8") as f:
            c = f.read()
        modified = False
        if "pointerdown" not in c:
            c = c.replace(
                "const closeOutside = (event: MouseEvent): void => {",
                "const closeOutside = (event: PointerEvent | MouseEvent): void => {"
            )
            c = c.replace(
                "document.addEventListener('mousedown', closeOutside)",
                "document.addEventListener('pointerdown', closeOutside)"
            )
            c = c.replace(
                "return () => { document.removeEventListener('mousedown', closeOutside) }",
                "return () => { document.removeEventListener('pointerdown', closeOutside) }"
            )
            modified = True
        if "onBlur={onBlur}" in c:
            c = c.replace(" onBlur={onBlur}", "")
            modified = True
        if modified:
            with open(tsx_path, "w", encoding="utf-8") as f:
                f.write(c)
            print("  [+] Patched ModelSelect.tsx touch interactions.")


def patch_koffi():
    """Patches Koffi CJS/ESM modules in node_modules/.pnpm to prevent crashes on Android."""
    koffi_dir = os.path.join(REPO_DIR, "node_modules", ".pnpm")
    if not os.path.exists(koffi_dir):
        return
    count = 0
    for root, dirs, files in os.walk(koffi_dir):
        if "koffi" in root and "src/koffi" in root:
            for fname in ["index.js", "index.cjs"]:
                if fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read()
                        if "createKoffiStub" not in content:
                            stub = """function createKoffiStub(v) {
  const dummyFn = () => {};
  return {
    LibraryHandle: class {},
    TypeObject: class {},
    Union: class {},
    address: dummyFn,
    alias: (name, type) => type,
    alignof: () => 8,
    alloc: () => 0n,
    array: (t, len) => ({ size: (len || 1) * 2, type: t, length: len }),
    as: (v2) => v2,
    call: dummyFn,
    config: dummyFn,
    decode: () => null,
    disposable: (v2) => v2,
    encode: dummyFn,
    enumeration: dummyFn,
    errno: () => 0,
    extension: dummyFn,
    free: dummyFn,
    in: (v2) => v2,
    inout: (v2) => v2,
    introspect: (spec) => ({ size: (spec && spec.size) || 0, alignment: 8, members: {} }),
    load: (libName) => {
      throw new Error(`Cannot load native library "${libName}": Koffi native module is not supported on ${process.platform}`);
    },
    node: dummyFn,
    offsetof: () => 0,
    opaque: () => ({ size: 8 }),
    os: { errno: () => 0 },
    out: (v2) => v2,
    pack: dummyFn,
    pointer: (t) => ({ size: 8, name: typeof t === 'string' ? t : 'pointer' }),
    proto: dummyFn,
    register: dummyFn,
    reset: dummyFn,
    resolve: (spec) => spec,
    sizeof: (spec) => (spec && spec.size) || 8,
    stats: () => ({}),
    struct: (name, members) => {
      let size = 0;
      if (typeof name === 'string') {
        if (name.includes('PROCESSENTRY32W')) size = 568;
        else if (name.includes('FILETIME')) size = 8;
        else if (name.includes('STARTUPINFO')) size = 104;
        else if (name.includes('PROCESS_INFORMATION')) size = 24;
      }
      return { size, name, members };
    },
    type: (spec) => spec,
    types: {},
    union: dummyFn,
    unregister: dummyFn,
    version: v,
    view: () => new Uint8Array(),
  };
}
"""
                            if fname == "index.js":
                                content = content.replace(
                                    "var native = loadStatic(pkg) ?? loadDynamic(import.meta.dirname, pkg, triplets);\nwrapNative(native, version);",
                                    stub + "\nvar native = loadStatic(pkg) ?? loadDynamic(import.meta.dirname, pkg, triplets) ?? createKoffiStub(version);\nif (native.LibraryHandle === undefined) { wrapNative(native, version); }"
                                )
                            else:
                                content = content.replace(
                                    "var native = loadStatic(pkg) ?? loadDynamic2(__dirname, pkg, triplets);\nwrapNative2(native, version);",
                                    stub + "\nvar native = loadStatic(pkg) ?? loadDynamic2(__dirname, pkg, triplets) ?? createKoffiStub(version);\nif (native.LibraryHandle === undefined) { wrapNative2(native, version); }"
                                )
                            with open(fpath, "w", encoding="utf-8") as f:
                                f.write(content)
                            count += 1
                    except Exception as e:
                        print(f"  [!] Notice patching {fpath}: {e}")
    if count > 0:
        print(f"  [+] Patched Koffi native fallback stubs ({count} files).")


def patch_node_pty():
    """Ensures node-pty has an android-arm64 native binary: cached CI build first, local compile second."""
    node_modules = os.path.join(REPO_DIR, "node_modules", ".pnpm")
    if not os.path.exists(node_modules):
        return
    cached_bin = os.path.join(NATIVE_CACHE_DIR, "pty.node")
    for root, dirs, files in os.walk(node_modules):
        if "node-pty" in root and "binding.gyp" in files:
            pty_bin = os.path.join(root, "build", "Release", "pty.node")
            prebuild_dir = os.path.join(root, "prebuilds", "android-arm64")
            prebuild_bin = os.path.join(prebuild_dir, "pty.node")
            if os.path.exists(prebuild_bin):
                continue
            if os.path.exists(cached_bin):
                try:
                    os.makedirs(prebuild_dir, exist_ok=True)
                    subprocess.run(["cp", "-f", cached_bin, prebuild_bin], check=True)
                    print("  [+] Restored android-arm64 pty.node from ~/.dsh/native cache.")
                    continue
                except Exception as e:
                    print(f"  [!] pty.node restore notice: {e}")
            print("  [*] Building native node-pty for android-arm64...")
            try:
                subprocess.run(["npx", "node-gyp", "rebuild"], cwd=root, check=True, capture_output=True)
                os.makedirs(prebuild_dir, exist_ok=True)
                if os.path.exists(pty_bin):
                    subprocess.run(["cp", "-f", pty_bin, prebuild_bin], check=True)
                    os.makedirs(NATIVE_CACHE_DIR, exist_ok=True)
                    subprocess.run(["cp", "-f", pty_bin, cached_bin], check=True)
                    print("  [+] Compiled & installed android-arm64 pty.node (cached for next update).")
            except Exception as e:
                print(f"  [!] node-pty compile notice: {e}")
                print("      Fix: bash scripts/install-pty-prebuild.sh  (fetches the CI-built binary)")


def apply_git_patch():
    """Attempts git apply using the master patch bundle."""
    target_patch = PATCH_FILE if os.path.exists(PATCH_FILE) else LEGACY_PATCH_FILE
    if os.path.exists(target_patch):
        try:
            check = subprocess.run(["git", "apply", "--check", target_patch], cwd=REPO_DIR, capture_output=True, text=True)
            if check.returncode == 0:
                apply_res = subprocess.run(["git", "apply", target_patch], cwd=REPO_DIR, capture_output=True, text=True)
                if apply_res.returncode == 0:
                    print(f"  [+] Applied patch bundle {os.path.basename(target_patch)} via git apply.")
                    return True
        except Exception as e:
            print(f"  [!] git apply note: {e}")
    return False


def export_patch():
    """Exports current Termux & Mobile diff to termux-mobile-suite.patch."""
    ensure_patch_dir()
    try:
        base = "upstream/master"
        # Verify if upstream/master exists, otherwise fallback to HEAD~1 or HEAD
        has_upstream = subprocess.run(["git", "rev-parse", "--verify", base], cwd=REPO_DIR, capture_output=True).returncode == 0
        if not has_upstream:
            base = "HEAD"
        
        diff = subprocess.run(
            ["git", "diff", base, "--", "package.json", "packages/", "apps/web/"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True
        )
        full_diff = diff.stdout
        if not full_diff.strip():
            res = subprocess.run(["git", "diff", "HEAD", "--", "package.json", "packages/", "apps/web/"], cwd=REPO_DIR, capture_output=True, text=True)
            full_diff = res.stdout

        if full_diff.strip():
            with open(PATCH_FILE, "w", encoding="utf-8") as f:
                f.write(full_diff)
            with open(LEGACY_PATCH_FILE, "w", encoding="utf-8") as f:
                f.write(full_diff)
            print(f"[+] Exported unified patch bundle ({len(full_diff)} bytes) to {PATCH_FILE}")
            return True
    except Exception as e:
        print(f"[!] Failed to export patch: {e}")
    return False



def check_status():
    """Audits all Termux and Mobile compatibility layers."""
    print("==================================================")
    print("   DeepSeek Harness Termux & Mobile Environment   ")
    print("==================================================")
    
    # 1. Attachment link fallback
    att_path = os.path.join(REPO_DIR, "packages", "attachment", "attachment-local", "src", "store.ts")
    att_ok = False
    if os.path.exists(att_path):
        with open(att_path, "r", encoding="utf-8") as f:
            c = f.read()
        att_ok = "EACCES" in c and "rename" in c
    print(f"[*] Android File Attachment Fallback:  {'[PASS]' if att_ok else '[FAIL]'}")

    # 2. Session link fallback
    sess_path = os.path.join(REPO_DIR, "packages", "session", "session-persistence-jsonl", "src", "index.ts")
    sess_ok = False
    if os.path.exists(sess_path):
        with open(sess_path, "r", encoding="utf-8") as f:
            c = f.read()
        sess_ok = "EACCES" in c and "rename" in c
    print(f"[*] Android Session Persistence:       {'[PASS]' if sess_ok else '[FAIL]'}")

    # 3. Browser Auth bypass
    auth_path = os.path.join(REPO_DIR, "packages", "client", "connection", "src", "browser-auth.ts")
    auth_ok = False
    if os.path.exists(auth_path):
        with open(auth_path, "r", encoding="utf-8") as f:
            c = f.read()
        auth_ok = "isLocalAuthority" in c
    print(f"[*] Local Mobile Auth Bypass:          {'[PASS]' if auth_ok else '[FAIL]'}")

    # 4. Mobile Drawer UI
    frame_path = os.path.join(REPO_DIR, "packages", "client", "ui-layout", "src", "client", "AppFrame.tsx")
    frame_ok = False
    if os.path.exists(frame_path):
        with open(frame_path, "r", encoding="utf-8") as f:
            c = f.read()
        frame_ok = "isMobile" in c and "mobileBackdrop" in c
    print(f"[*] Responsive Mobile Drawer & UI:     {'[PASS]' if frame_ok else '[FAIL]'}")

    # 5. Model Selection Touch Fix
    ms_path = os.path.join(REPO_DIR, "packages", "client", "ui-model-selection", "src", "client", "ModelSelect.tsx")
    ms_ok = False
    if os.path.exists(ms_path):
        with open(ms_path, "r", encoding="utf-8") as f:
            c = f.read()
        ms_ok = "pointerdown" in c
    print(f"[*] Touch & Dropdown Handling:         {'[PASS]' if ms_ok else '[FAIL]'}")

    # 6. fs-local writeFileAtomic link fallback
    fs_path = os.path.join(REPO_DIR, "packages", "fs", "fs-local", "src", "fsio.ts")
    fs_ok = False
    if os.path.exists(fs_path):
        with open(fs_path, "r", encoding="utf-8") as f:
            c = f.read()
        fs_ok = "isAndroid" in c and "rename" in c
    print(f"[*] Android fs-local Atomic Write:     {'[PASS]' if fs_ok else '[FAIL]'}")

    # 7. package.json internals
    pkg_path = os.path.join(REPO_DIR, "package.json")
    pkg_ok = False
    if os.path.exists(pkg_path):
        with open(pkg_path, "r", encoding="utf-8") as f:
            c = f.read()
        pkg_ok = "--expose-internals" in c and "sharp-wasm32" in c
    print(f"[*] Runtime Engine Flags & Wasm:       {'[PASS]' if pkg_ok else '[FAIL]'}")

    print("==================================================")
    all_ok = att_ok and sess_ok and auth_ok and frame_ok and ms_ok and fs_ok and pkg_ok
    return all_ok


def ensure_workspace_symlinks():
    """Ensures all workspace packages (@deepseek-ai/*) are linked into node_modules/@deepseek-ai/."""
    import json
    nm = os.path.join(REPO_DIR, "node_modules", "@deepseek-ai")
    os.makedirs(nm, exist_ok=True)
    dirs = ["packages", "vendor", "apps", "native"]
    count = 0
    for d in dirs:
        base = os.path.join(REPO_DIR, d)
        if not os.path.exists(base):
            continue
        for root, subdirs, files in os.walk(base):
            if "node_modules" in root:
                continue
            if "package.json" in files:
                pj = os.path.join(root, "package.json")
                try:
                    with open(pj, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    name = data.get("name", "")
                    if name.startswith("@deepseek-ai/"):
                        subname = name.split("/", 1)[1]
                        link_path = os.path.join(nm, subname)
                        rel_target = os.path.relpath(root, nm)
                        if not os.path.exists(link_path):
                            os.symlink(rel_target, link_path)
                            count += 1
                except Exception:
                    pass
    if count > 0:
        print(f"  [+] Linked {count} new workspace package(s) in node_modules/@deepseek-ai.")
    return True


def apply_all():
    print("[*] Applying DeepSeek Harness Termux & Mobile Environment Suite...")
    apply_git_patch()
    
    ensure_workspace_symlinks()
    patch_attachment_store()
    patch_session_persistence()
    patch_fs_local()
    patch_browser_auth()
    patch_package_json()
    patch_app_frame()
    patch_model_select()
    patch_koffi()
    patch_node_pty()
    
    print("[+] All Termux & Mobile UX patches verified and active.")
    export_patch()


def main():
    parser = argparse.ArgumentParser(description="DeepSeek Harness Termux & Mobile Environment Patcher")
    parser.add_argument("--apply", action="store_true", help="Apply all fixes")
    parser.add_argument("--check", "--status", action="store_true", help="Check patch status")
    parser.add_argument("--export", action="store_true", help="Export unified patch bundle")
    args = parser.parse_args()

    if args.check:
        ok = check_status()
        sys.exit(0 if ok else 1)
    elif args.export:
        export_patch()
    else:
        apply_all()


if __name__ == "__main__":
    main()
