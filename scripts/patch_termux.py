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
7. @vscode/ripgrep android-arm64 shim linking Termux's ripgrep (glob and grep tools)
8. fs-ext android-arm64 addon for the session write lease (cached, else compiled)
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
    """Applies the Android edits to packages/attachment/attachment-local/src/store.ts.

    Each edit pairs the exact upstream text with its replacement, so a merge that
    reshapes the file reports an unmatched anchor instead of silently leaving the
    tree unpatched.
    """
    path = os.path.join(REPO_DIR, "packages", "attachment", "attachment-local", "src", "store.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    modified = False
    # Keep whatever upstream imports and add the two Android fallbacks need.
    imports = re.search(r"import \{([^}]*)\} from 'node:fs/promises'", c)
    if imports is None:
        print("  [!] attachment store: fs/promises import not found — symlink/rename cannot be added")
    else:
        present = {name.strip() for name in imports.group(1).split(",") if name.strip()}
        wanted = present | {"symlink", "rename"}
        if wanted != present:
            c = c.replace(imports.group(0), "import { " + ", ".join(sorted(wanted)) + " } from 'node:fs/promises'", 1)
            modified = True

    # link() is denied inside the Android app sandbox, so the publish path falls
    # back to rename() for a staged object and to copyFile() for an alias, whose
    # source must survive.
    alias_upstream = """    try {
      await link(source, target)
    } catch (error) {
      /* v8 ignore next -- Private same-filesystem directories make EEXIST the only recoverable link race. */
      if (!(error instanceof Error && 'code' in error && error.code === 'EEXIST')) throw error
      if (await digestFile(target) !== sha256) {
        throw new AttachmentError('Stored attachment failed integrity verification.', 'ATTACHMENT_CORRUPT')
      }
    }
"""
    alias_android = """    try {
      await link(source, target)
    } catch (error) {
      if (error instanceof Error && 'code' in error && (error.code === 'EACCES' || error.code === 'EPERM' || error.code === 'EXDEV' || error.code === 'ENOSYS')) {
        // An alias is a second name for one object: Android denies link(), so
        // the fallback shares the bytes through a symlink rather than doubling
        // them with a copy, which would also break the store's dedup accounting.
        await symlink(source, target)
      } else if (error instanceof Error && 'code' in error && error.code === 'EEXIST') {
        if (await digestFile(target) !== sha256) {
          throw new AttachmentError('Stored attachment failed integrity verification.', 'ATTACHMENT_CORRUPT')
        }
      } else {
        throw error
      }
    }
"""
    link_upstream = """    try {
      await link(staged.path, target)
    } catch (error) {
      /* v8 ignore next -- Private same-filesystem directories make EEXIST the only recoverable link race. */
      if (!(error instanceof Error && 'code' in error && error.code === 'EEXIST')) throw error
      if (await digestFile(target) !== staged.sha256) {
        throw new AttachmentError('Stored attachment failed integrity verification.', 'ATTACHMENT_CORRUPT')
      }
    }
"""
    link_android = """    let renamed = false
    try {
      await link(staged.path, target)
    } catch (error) {
      if (error instanceof Error && 'code' in error && (error.code === 'EACCES' || error.code === 'EPERM' || error.code === 'EXDEV' || error.code === 'ENOSYS')) {
        await rename(staged.path, target)
        renamed = true
      } else if (error instanceof Error && 'code' in error && error.code === 'EEXIST') {
        if (await digestFile(target) !== staged.sha256) {
          throw new AttachmentError('Stored attachment failed integrity verification.', 'ATTACHMENT_CORRUPT')
        }
      } else {
        throw error
      }
    }
"""
    unlink_upstream = """    // Windows shares the read-only attribute across hard links and refuses to
    // unlink either name once it is set, so discard the staging name first.
    await unlink(staged.path)
"""
    unlink_android = """    // Windows shares the read-only attribute across hard links and refuses to
    // unlink either name once it is set, so discard the staging name first.
    // The rename fallback moved that name onto the target, so only a link or a
    // deduplicated observation leaves a staging entry to discard.
    if (!renamed) await unlink(staged.path)
"""
    sync_upstream = """  const handle = await open(path, constants.O_RDONLY)
"""
    sync_android = """  let handle
  try {
    handle = await open(path, constants.O_RDONLY)
  } catch (error) {
    // Android's app sandbox refuses to open /data/data and every ancestor above
    // it, which the DSH_HOME walk reaches three levels above the harness tree. A
    // directory this process cannot open is one it cannot have created, so its
    // entry was already durable before the walk started.
    if (error instanceof Error && 'code' in error && (error.code === 'EACCES' || error.code === 'EPERM')) return
    throw error
  }
"""

    for marker, upstream, android, label in (
        ("symlink(source, target)", alias_upstream, alias_android, "alias copy fallback"),
        ("renamed = true", link_upstream, link_android, "staged rename fallback"),
        ("if (!renamed) await unlink(staged.path)", unlink_upstream, unlink_android, "guarded staging unlink"),
        ("Android's app sandbox refuses to open /data/data", sync_upstream, sync_android, "ancestor fsync guard"),
    ):
        if marker in c:
            continue
        if upstream not in c:
            print(f"  [!] attachment store: {label} anchor did not match — reapply by hand against store.ts")
            continue
        c = c.replace(upstream, android, 1)
        modified = True

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched attachment store for Android (link fallback, staging unlink, ancestor fsync).")
    return True


def patch_session_persistence():
    """Patches packages/session/session-persistence-jsonl/src/index.ts for Android link fallback."""
    path = os.path.join(REPO_DIR, "packages", "session", "session-persistence-jsonl", "src", "index.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    modified = False
    # Merge rename() into whatever upstream imports: pinning the whole list let a
    # dropped name (0.1.3 removed readFile) miss silently, leaving the fallback
    # calling an unimported rename and failing the build with TS2552.
    imports = re.search(r"import \{([^}]*)\} from 'node:fs/promises'", c)
    if imports is None:
        print("  [!] session persistence: fs/promises import not found — rename() cannot be added")
    else:
        present = {name.strip() for name in imports.group(1).split(",") if name.strip()}
        wanted = present | {"rename"}
        if wanted != present:
            c = c.replace(imports.group(0), "import { " + ", ".join(sorted(wanted)) + " } from 'node:fs/promises'", 1)
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
        c, count = pat.subn(repl, c, count=1)
        if count == 0:
            print("  [!] session persistence: link fallback anchor did not match — reapply by hand against index.ts")
        else:
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
    """Patches packages/client/ui-layout/src/client/AppFrame.tsx for the mobile drawer.

    Adaptive to upstream renames: the old suite targeted `cols.details` /
    `actions.closeDetails`; the current upstream renamed that panel to
    `rightbar` (`cols.rightbar` / `actions.closeRightbar`) and dropped the
    `setNarrow` effect the old definition anchor depended on. Every edit is
    anchored against the live file and reported, so a missed anchor is visible
    instead of silently producing an uncompilable half-patch.
    """
    tsx_path = os.path.join(REPO_DIR, "packages", "client", "ui-layout", "src", "client", "AppFrame.tsx")
    if not os.path.exists(tsx_path):
        return
    with open(tsx_path, "r", encoding="utf-8") as f:
        c = f.read()
    edits = []

    # 0. Migrate stale references left by an older suite run against a
    #    previous upstream shape (details panel → rightbar panel). Runs even
    #    when the file already looks patched, otherwise a merge leaves the old
    #    identifiers in place and the client build fails on CI.
    if "cols.details" in c and "cols.rightbar" in c:
        c = c.replace("cols.details", "cols.rightbar")
        edits.append("cols.details→cols.rightbar")
    if "actions.closeDetails" in c:
        # The close action lives in the store, not this file — ask stores.ts
        # which name upstream currently ships (closeDetails is gone as of the
        # rightbar rename).
        stores_path = os.path.join(REPO_DIR, "packages", "client", "ui-layout", "src", "client", "stores.ts")
        store_c = ""
        if os.path.exists(stores_path):
            with open(stores_path, "r", encoding="utf-8") as f:
                store_c = f.read()
        if "closeRightbar" in store_c or "closeDetails" not in store_c:
            c = c.replace("actions.closeDetails", "actions.closeRightbar")
            edits.append("closeDetails→closeRightbar")
    if "const isMobile" in c and "mobileBackdrop" in c and not edits:
        return  # already patched, nothing stale to migrate

    # 1. Define isMobile next to the narrow breakpoint (anchor survives across
    #    upstream versions; only the following statement differs).
    if "const isMobile" not in c:
        anchor = "const narrow = viewport < SIDEBAR_AUTO_COLLAPSE"
        if anchor in c:
            c = c.replace(
                anchor,
                anchor + "\n  const isMobile = viewport <= 768",
                1,
            )
            edits.append("isMobile definition")

    # 2. Sidebar slot: drawer always expanded, fixed 280px width on mobile.
    old_slot = "{renderSlot('sidebar', {\n          collapsed: sidebarCollapsed,\n          width: cols.sidebar,\n        })}"
    new_slot = "{renderSlot('sidebar', {\n          collapsed: isMobile ? false : sidebarCollapsed,\n          width: isMobile ? 280 : cols.sidebar,\n        })}"
    if old_slot in c:
        c = c.replace(old_slot, new_slot, 1)
        edits.append("sidebar slot params")

    # 3. Backdrop + collapsed-state toggle button. The right panel closed on
    #    backdrop tap uses whichever close action upstream currently ships.
    if "mobileBackdrop" not in c:
        close_action = "closeRightbar" if "closeRightbar" in c else "closeDetails"
        track_col = "cols.rightbar" if "cols.rightbar" in c else "cols.details"
        backdrop_code = f"""      {{/* Mobile drawer backdrop */}}
      {{isMobile && (!sidebarCollapsed || {track_col} > 0) && (
        <div
          className={{css.mobileBackdrop}}
          onClick={{() => {{
            if (!sidebarCollapsed) actions.toggleSidebar()
            if ({track_col} > 0) actions.{close_action}()
          }}}}
          aria-hidden="true"
        />
      )}}

      {{/* Mobile sidebar toggle button when collapsed */}}
      {{isMobile && sidebarCollapsed && (
        <button
          type="button"
          className={{css.mobileSidebarToggle}}
          aria-label="Toggle sidebar"
          onClick={{() => {{ actions.toggleSidebar() }}}}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12"></line>
            <line x1="3" y1="6" x2="21" y2="6"></line>
            <line x1="3" y1="18" x2="21" y2="18"></line>
          </svg>
        </button>
      )}}

      <div className={{css.sidebarCol}}>"""
        anchor = "      <div className={css.sidebarCol}>"
        if anchor in c:
            c = c.replace(anchor, backdrop_code, 1)
            edits.append("mobile backdrop + toggle button")

    # 4. Desktop-only sidebar drag handle (the CSS also hides .handle on
    #    mobile; this keeps the DOM honest).
    old_handle = '{!sidebarCollapsed && <DragHandle side="sidebar" left={cols.sidebar} onStart={onSidebarStart} onDrag={onSidebarDrag} onEnd={onDragEnd} />} '
    old_handle = old_handle.rstrip()
    new_handle = '{!sidebarCollapsed && !isMobile && <DragHandle side="sidebar" left={cols.sidebar} onStart={onSidebarStart} onDrag={onSidebarDrag} onEnd={onDragEnd} />} '
    new_handle = new_handle.rstrip()
    if old_handle in c and new_handle not in c:
        c = c.replace(old_handle, new_handle, 1)
        edits.append("sidebar drag handle gating")

    if edits:
        with open(tsx_path, "w", encoding="utf-8") as f:
            f.write(c)
        print(f"  [+] Patched AppFrame.tsx mobile responsive drawer ({', '.join(edits)}).")
    elif "const isMobile" not in c or "mobileBackdrop" not in c:
        print("  [!] AppFrame.tsx anchors did not match — mobile drawer NOT applied. File may have changed upstream; update patch_app_frame().")


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


def patch_fs_ext():
    """Ensures fs-ext has its android-arm64 addon: cached build first, local compile second.

    Upstream 0.1.3 took fs-ext for the cross-process write lease. It builds from
    source in an install script, which every Termux install skips with
    --ignore-scripts, so session-persistence-jsonl cannot load without this.
    """
    node_modules = os.path.join(REPO_DIR, "node_modules", ".pnpm")
    if not os.path.exists(node_modules):
        return
    cached = os.path.join(NATIVE_CACHE_DIR, "fs_ext.node")
    for entry in os.listdir(node_modules):
        if not entry.startswith("fs-ext@"):
            continue
        pkg = os.path.join(node_modules, entry, "node_modules", "fs-ext")
        built = os.path.join(pkg, "build", "Release", "fs_ext.node")
        if os.path.exists(built) or not os.path.exists(os.path.join(pkg, "binding.gyp")):
            continue
        if os.path.exists(cached):
            try:
                os.makedirs(os.path.dirname(built), exist_ok=True)
                subprocess.run(["cp", "-f", cached, built], check=True)
                print("  [+] Restored android-arm64 fs_ext.node from ~/.dsh/native cache.")
                continue
            except Exception as e:
                print(f"  [!] fs_ext.node restore notice: {e}")
        print("  [*] Building fs-ext for android-arm64...")
        try:
            subprocess.run(["npx", "node-gyp", "rebuild"], cwd=pkg, check=True, capture_output=True)
            if os.path.exists(built):
                os.makedirs(NATIVE_CACHE_DIR, exist_ok=True)
                subprocess.run(["cp", "-f", built, cached], check=True)
                print("  [+] Compiled & cached android-arm64 fs_ext.node.")
        except Exception as e:
            print(f"  [!] fs-ext compile notice: {e}")
            print("      The session write lease needs it: cd into the package and run `npx node-gyp rebuild`")


def patch_ripgrep():
    """Links Termux's ripgrep in as @vscode/ripgrep-android-arm64, which npm does not publish."""
    node_modules = os.path.join(REPO_DIR, "node_modules", ".pnpm")
    if not os.path.exists(node_modules):
        return
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    system_rg = os.path.join(prefix, "bin", "rg")
    if not os.path.exists(system_rg):
        print("  [!] ripgrep missing — the glob and grep tools need it: pkg install ripgrep")
        return
    manifest = (
        '{\n'
        '  "name": "@vscode/ripgrep-android-arm64",\n'
        '  "version": "1.18.0",\n'
        '  "description": "Termux shim: npm publishes no Android platform package, so bin/rg links to the system ripgrep.",\n'
        '  "os": ["android"],\n'
        '  "cpu": ["arm64"]\n'
        '}\n'
    )
    count = 0
    for entry in os.listdir(node_modules):
        # Only the dispatcher package; the platform packages share its prefix.
        if not entry.startswith("@vscode+ripgrep@"):
            continue
        shim = os.path.join(node_modules, entry, "node_modules", "@vscode", "ripgrep-android-arm64")
        binary = os.path.join(shim, "bin", "rg")
        if os.path.islink(binary) or os.path.exists(binary):
            continue
        try:
            os.makedirs(os.path.join(shim, "bin"), exist_ok=True)
            os.symlink(system_rg, binary)
            with open(os.path.join(shim, "package.json"), "w", encoding="utf-8") as f:
                f.write(manifest)
            count += 1
        except Exception as e:
            print(f"  [!] ripgrep shim notice: {e}")
    if count > 0:
        print(f"  [+] Linked Termux ripgrep into {count} @vscode/ripgrep copy(ies).")


def patch_settings_mobile():
    """Reapplies the mobile settings sheet to packages/client/ui-settings-general.

    Upstream owns both files and rewrote the stylesheet against a desktop figma
    spec, so a merge resolved to upstream drops the sheet while leaving the TSX
    referencing classes that no longer exist — the failure that broke the
    settings screen in both views on 2026-09-01. The CSS block lives in
    patches/settings-mobile.css so it stays reviewable.
    """
    base = os.path.join(REPO_DIR, "packages", "client", "ui-settings-general")
    tsx_path = os.path.join(base, "src", "client", "SettingsRoot.tsx")
    css_path = os.path.join(base, "src", "client", "SettingsRoot.module.css")
    manifest_path = os.path.join(base, "package.json")
    block_path = os.path.join(PATCH_DIR, "settings-mobile.css")
    if not os.path.exists(tsx_path) or not os.path.exists(css_path):
        return False

    applied = []
    with open(tsx_path, "r", encoding="utf-8") as f:
        tsx = f.read()

    header_jsx = """        <div className={css.mobileHeader}>
          <span className={css.mobileTitle}>{renderSlot('settings.header', {})}</span>
          <div className={css.mobileActions}>
            {renderSlot('settings.action', {})}
            <button type="button" className={css.mobileClose} onClick={onClose} aria-label="Close">
              <IconCloseOutline16 size={16} />
            </button>
          </div>
        </div>
"""
    nav_open = "        <nav className={css.nav}>\n"
    panel_open = '  return (\n    <div className={css.overlay} role="presentation">\n'
    react_import = "import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'\n"
    panel_tail = "      </div>\n    </div>\n  )\n}\n"

    for marker, upstream, patched, label in (
        ("from 'react-dom'", react_import, react_import + "import { createPortal } from 'react-dom'\n", "react-dom import"),
        # The panel becomes a value so it can be portalled to document.body.
        ("const panel = (", panel_open, panel_open.replace("  return (", "  const panel = ("), "panel binding"),
        ("css.mobileHeader", nav_open, header_jsx + nav_open, "mobile header row"),
        (
            "createPortal(panel, document.body)",
            panel_tail,
            "      </div>\n    </div>\n  )\n\n  if (typeof document !== 'undefined') {\n    return createPortal(panel, document.body)\n  }\n  return panel\n}\n",
            "portal render",
        ),
    ):
        if marker in tsx:
            continue
        if upstream not in tsx:
            print(f"  [!] settings sheet: {label} anchor did not match — reapply by hand against SettingsRoot.tsx")
            continue
        tsx = tsx.replace(upstream, patched, 1)
        applied.append(label)
    if applied:
        with open(tsx_path, "w", encoding="utf-8") as f:
            f.write(tsx)

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    if ".mobileHeader" not in css:
        if not os.path.exists(block_path):
            print("  [!] settings sheet: patches/settings-mobile.css is missing — the mobile CSS cannot be restored")
        else:
            with open(block_path, "r", encoding="utf-8") as f:
                block = f.read()
            with open(css_path, "w", encoding="utf-8") as f:
                f.write(css + block)
            applied.append("mobile stylesheet")

    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = f.read()
        changed = False
        for anchor, addition in (
            ('    "@types/react": "~18.3.1",\n', '    "@types/react-dom": "~18.3.1",\n'),
            ('    "react": "^18.2.0",\n', '    "react-dom": "^18.2.0",\n'),
        ):
            if addition.strip() in manifest or anchor not in manifest:
                continue
            manifest = manifest.replace(anchor, anchor + addition, 1)
            changed = True
        if changed:
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest)
            applied.append("react-dom dependency")

    if applied:
        print(f"  [+] Restored the mobile settings sheet ({', '.join(applied)}).")
    return True


def patch_llm_pi_ai_gateway():
    """Reapplies the custom-gateway edits to the pi-ai adapter and the LLM error classifier.

    The harness sends attribution headers that win over a route's own by design.
    Gateways declared in ~/.dsh/settings.yaml (agentrouter, justwoker) admit only
    a recognized client, so a joined User-Agent is refused; these edits let the
    route's header replace attribution on requests and on model discovery alike,
    and classify the billing statuses those gateways answer with as terminal
    quota. Upstream's specs for these functions assert the opposite precedence.
    """
    files = {
        "adapter": os.path.join(REPO_DIR, "packages", "llm", "llm-pi-ai", "src", "adapter.ts"),
        "discovery": os.path.join(REPO_DIR, "packages", "llm", "llm-pi-ai", "src", "discovery.ts"),
        "stream": os.path.join(REPO_DIR, "packages", "llm", "llm-pi-ai", "src", "stream.ts"),
        "error": os.path.join(REPO_DIR, "packages", "llm", "llm", "src", "error.ts"),
    }
    if not all(os.path.exists(p) for p in files.values()):
        return False

    edits = {
        "adapter": [(
            "const configured = new Set(",
            """/** Merge deployment headers while removing case-insensitive attribution collisions. */
function requestHeaders(headers: Readonly<Record<string, string>> | undefined): Record<string, string> {
  const attribution = attributionHeaders()
  const reserved = new Set(Object.keys(attribution).map(name => name.toLowerCase()))
  return {
    ...Object.fromEntries(Object.entries(headers ?? {}).filter(([name]) => !reserved.has(name.toLowerCase()))),
    ...attribution,
  }
}
""",            """/**
 * Merge Harness attribution with a route's deployment headers, letting the
 * route win per header name. HTTP field names are case-insensitive, so an
 * attribution header a route restates under different capitalization is
 * dropped rather than merged: a gateway that admits only a recognized client
 * rejects both a comma-joined `User-Agent` and whichever single value a
 * downstream normalizer happened to keep.
 * @param headers - the route's configured headers, when it declares any.
 * @returns headers for the provider request, each name present once.
 */
function requestHeaders(headers: Readonly<Record<string, string>> | undefined): Record<string, string> {
  const configured = new Set(Object.keys(headers ?? {}).map(name => name.toLowerCase()))
  return {
    ...Object.fromEntries(Object.entries(attributionHeaders()).filter(([name]) => !configured.has(name.toLowerCase()))),
    ...headers,
  }
}
""",
            "request header precedence",
        ), (
            "const configured = new Set(",
            # The fork reached route-wins precedence first, in a form that still
            # emits two entries when a route restates a name in another case.
            """/** Merge deployment headers with provider defaults while allowing custom user-agent overrides. */
function requestHeaders(headers: Readonly<Record<string, string>> | undefined): Record<string, string> {
  return {
    ...attributionHeaders(),
    ...headers,
  }
}
""",
            """/**
 * Merge Harness attribution with a route's deployment headers, letting the
 * route win per header name. HTTP field names are case-insensitive, so an
 * attribution header a route restates under different capitalization is
 * dropped rather than merged: a gateway that admits only a recognized client
 * rejects both a comma-joined `User-Agent` and whichever single value a
 * downstream normalizer happened to keep.
 * @param headers - the route's configured headers, when it declares any.
 * @returns headers for the provider request, each name present once.
 */
function requestHeaders(headers: Readonly<Record<string, string>> | undefined): Record<string, string> {
  const configured = new Set(Object.keys(headers ?? {}).map(name => name.toLowerCase()))
  return {
    ...Object.fromEntries(Object.entries(attributionHeaders()).filter(([name]) => !configured.has(name.toLowerCase()))),
    ...headers,
  }
}
""",
            "request header precedence (fork base)",
        )],
        "discovery": [
            (
                "// Attribution first so a route's own",
                "    const headers = new Headers(stored?.headers === undefined ? undefined : Object.entries(stored.headers))\n",
                """    // Attribution first so a route's own `User-Agent` overrides it, exactly as
    // it does on a model request: a gateway that admits only a recognized
    // client would otherwise serve that route's requests while refusing to
    // list its models.
    const headers = new Headers(Object.entries(attributionHeaders()))
    if (stored?.headers !== undefined) {
      for (const [name, value] of Object.entries(stored.headers)) headers.set(name, value)
    }
""",
                "discovery header precedence",
            ),
            (
                "// Attribution first so a route's own",
                "    for (const [name, value] of Object.entries(attributionHeaders())) headers.set(name, value)\n",
                "",
                "discovery attribution override removal",
            ),
        ],
        "stream": [(
            "/\\b402\\b/.test(message)",
            "  if (isQuotaExceededError(message)) return QUOTA_EXCEEDED_CODE\n",
            """  // 402 Payment Required is the billing status OpenAI-compatible gateways
  // answer with when an account's credit, balance, or budget is spent, whatever
  // wording their body carries.
  if (/\\b402\\b/.test(message) || isQuotaExceededError(message)) return QUOTA_EXCEEDED_CODE
""",
            "402 as terminal quota",
        )],
        "error": [(
            "(?:has|have|is|are|was|were)",
            """    || /\\b(?:quota|usage[\\s_-]+limit)[\\s_-]+(?:exceeded|exhausted|reached)\\b/i.test(detail)""",
            """    || /\\b(?:quota|usage[\\s_-]+limit)(?:[\\s_-]+(?:has|have|is|are|was|were)(?:[\\s_-]+been)?)?[\\s_-]+(?:exceeded|exhausted|reached)\\b/i.test(detail)""",
            "quota wording with a copula",
        ), (
            "(?:balance|credits?)(?:[\\s_-]+(?:has",
            """    || /\\b(?:balance|credits?)[\\s_-]+(?:exhausted|depleted)\\b/i.test(detail)""",
            """    || /\\b(?:balance|credits?)(?:[\\s_-]+(?:has|have|is|are|was|were)(?:[\\s_-]+been)?)?[\\s_-]+(?:exhausted|depleted)\\b/i.test(detail)""",
            "balance wording with a copula",
        )],
    }

    applied = []
    for key, path in files.items():
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        changed = False
        pending = {}
        for marker, upstream, patched, label in edits[key]:
            # A removal is done when its upstream line is gone; every other edit
            # is done when its marker is present.
            if (upstream not in c) if patched == "" else (marker in c):
                continue
            if upstream not in c:
                # A sibling entry may carry the variant this base actually has,
                # so defer the warning until every variant has had its turn.
                pending.setdefault(marker, label)
                continue
            c = c.replace(upstream, patched, 1)
            changed = True
            applied.append(label)
        for marker, label in pending.items():
            if marker not in c:
                print(f"  [!] pi-ai gateway: {label} anchor did not match — reapply by hand against {os.path.basename(path)}")
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                f.write(c)

    if applied:
        print(f"  [+] Reapplied the pi-ai gateway edits ({', '.join(applied)}).")
    return True


def patch_user_questions_mobile():
    """Patches packages/client/ui-user-questions for mobile viewport clearance and button wrapping.

    Fixes the Ask User and Plan Review floating decision footers on mobile screens
    so the submit button and feedback text clear the viewport and wrap naturally.
    """
    base = os.path.join(REPO_DIR, "packages", "client", "ui-user-questions", "src", "client")
    qc_css = os.path.join(base, "QuestionComposer.module.css")
    pr_css = os.path.join(base, "PlanReviewPanel.module.css")
    applied = []

    for path, label in ((qc_css, "QuestionComposer"), (pr_css, "PlanReviewPanel")):
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()

        changed = False
        if "padding-left: var(--dsh-composer-side-clearance);" not in c:
            anchor = "@media (max-width: 720px) {\n  .card {"
            replacement = "@media (max-width: 720px) {\n  .frame {\n    padding-left: var(--dsh-composer-side-clearance);\n    padding-right: var(--dsh-composer-side-clearance);\n  }\n\n  .card {"
            if anchor in c:
                c = c.replace(anchor, replacement, 1)
                changed = True
                applied.append(f"{label} clearance")

        if "flex-wrap: wrap;" not in c:
            old_footer = "  .footer {\n    align-items: flex-end;"
            new_footer = "  .footer {\n    flex-wrap: wrap;\n    gap: 8px 12px;\n    align-items: center;"
            if old_footer in c:
                c = c.replace(old_footer, new_footer, 1)
                changed = True

            if label == "QuestionComposer" and ".footerActions {" in c:
                old_fa = "  .footerActions {\n    flex-shrink: 0;\n  }"
                new_fa = "  .feedback {\n    order: -1;\n    width: 100%;\n    min-height: 0;\n    text-align: left;\n    word-break: break-word;\n  }\n\n  .feedback:empty {\n    display: none;\n  }\n\n  .footerActions {\n    display: flex;\n    align-items: center;\n    flex-wrap: wrap;\n    gap: 8px;\n    flex-shrink: 0;\n    margin-left: auto;\n  }"
                if old_fa in c:
                    c = c.replace(old_fa, new_fa, 1)
                    changed = True
                    applied.append(f"{label} button wrapping")
            elif label == "PlanReviewPanel" and ".feedback {" not in c:
                old_tail = "  .footer {\n    flex-wrap: wrap;\n    gap: 8px 12px;\n    align-items: center;\n    padding: 8px 12px 10px;\n  }\n}"
                new_tail = "  .footer {\n    flex-wrap: wrap;\n    gap: 8px 12px;\n    align-items: center;\n    padding: 8px 12px 10px;\n  }\n\n  .feedback {\n    order: -1;\n    width: 100%;\n    min-height: 0;\n    word-break: break-word;\n  }\n\n  .feedback:empty {\n    display: none;\n  }\n\n  .actions {\n    display: flex;\n    align-items: center;\n    flex-wrap: wrap;\n    gap: 8px;\n    margin-left: auto;\n  }\n}"
                if old_tail in c:
                    c = c.replace(old_tail, new_tail, 1)
                    changed = True
                    applied.append(f"{label} actions wrapping")

        if changed:
            with open(path, "w", encoding="utf-8") as f:
                f.write(c)

    if applied:
        print(f"  [+] Patched user-questions mobile clearance ({', '.join(applied)}).")
    return True


def patch_trajectory_mobile():
    """Patches packages/client/ui-trajectory for mobile readability, z-index isolation, and smooth scrolling."""
    css_path = os.path.join(REPO_DIR, "packages", "client", "ui-trajectory", "src", "client", "TrajectoryTable.module.css")
    if not os.path.exists(css_path):
        return False
    with open(css_path, "r", encoding="utf-8") as f:
        c = f.read()

    changed = False
    applied = []

    # 1. Isolation on tablePane so request dots and table controls do not bleed through details
    if "container: trajectory-table / inline-size;\n  isolation: isolate;" not in c:
        anchor = "container: trajectory-table / inline-size;"
        if anchor in c:
            c = c.replace(anchor, "container: trajectory-table / inline-size;\n  isolation: isolate;", 1)
            changed = True
            applied.append("tablePane isolation")

    # 2. Overview items wrapping without ellipsis truncation
    if ".overview dd {\n  min-width: 0;\n  margin: 0;\n  color: var(--dsw-alias-label-primary);\n  white-space: normal;" not in c:
        old_dd = ".overview dd {\n  min-width: 0;\n  margin: 0;\n  overflow: hidden;\n  color: var(--dsw-alias-label-primary);\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}"
        new_dd = ".overview dd {\n  min-width: 0;\n  margin: 0;\n  color: var(--dsw-alias-label-primary);\n  white-space: normal;\n  word-break: break-word;\n  overflow-wrap: anywhere;\n  line-height: 18px;\n}"
        if old_dd in c:
            c = c.replace(old_dd, new_dd, 1)
            changed = True
            applied.append("overview text wrap")

    # 3. Overview preview touch scrolling
    if "overscroll-behavior: auto;\n  -webkit-overflow-scrolling: touch;" not in c:
        old_prev = ".overviewPreview {\n  flex: 1;\n  min-height: 0;\n  overflow: auto;\n  overscroll-behavior: contain;\n  background: var(--dsw-alias-bg-layer-1);\n}"
        new_prev = ".overviewPreview {\n  box-sizing: border-box;\n  max-height: 280px;\n  overflow: auto;\n  overscroll-behavior: auto;\n  -webkit-overflow-scrolling: touch;\n  background: var(--dsw-alias-bg-layer-1);\n}"
        if old_prev in c:
            c = c.replace(old_prev, new_prev, 1)
            changed = True
            applied.append("overviewPreview touch scroll")

    # 4. Mobile details full-width overlay and z-index 20
    if "z-index: 20;\n    top: 0;\n    right: 0;\n    bottom: 0;\n    left: 0;\n    width: 100% !important;" not in c:
        old_details = """@media (max-width: 760px) {
  .details {
    position: absolute;
    z-index: 5;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(92%, 420px);
    max-width: 92%;
    border-left-color: var(--dsw-alias-border-l3);
    box-shadow: -12px 0 32px rgba(0, 0, 0, 0.14);
  }
}"""
        new_details = """@media (max-width: 760px) {
  .details {
    position: absolute;
    z-index: 20;
    top: 0;
    right: 0;
    bottom: 0;
    left: 0;
    width: 100% !important;
    max-width: 100% !important;
    border-left: none;
    box-shadow: none;
  }

  .detailsResizeHandle {
    display: none;
  }

  .detailsHeader {
    height: 44px;
    padding: 0 8px 0 12px;
  }

  .close {
    width: 36px;
    height: 36px;
    font-size: 20px;
    line-height: 20px;
  }

  .detailTabs {
    height: 38px;
    padding: 0 4px;
  }

  .detailTab {
    padding: 0 12px;
    font-size: 13px;
  }

  .detailBodySummary {
    padding-bottom: calc(24px + var(--dsh-trajectory-bottom-clearance, 168px));
  }

  .overview {
    padding: 8px 0;
  }

  .overview > div {
    grid-template-columns: 88px minmax(0, 1fr);
    padding: 3px 12px;
    gap: 8px;
  }

  .overviewHeading {
    min-height: 30px;
    padding: 4px 12px;
  }

  .overviewPreview {
    max-height: 320px;
    overscroll-behavior: auto;
  }

  .payload {
    padding: 10px 12px;
    font-size: 12px;
    line-height: 18px;
  }

  .resultBlocks {
    padding: 10px 12px;
    gap: 8px;
  }

  .resultBlockText {
    font-size: 12px;
    line-height: 18px;
  }

  .schemaIntro {
    padding: 10px 12px 6px;
  }

  .schemaParametersTitle {
    padding: 4px 12px 2px;
  }

  .markdownPayload {
    padding: 12px;
  }

  .markdownPreview {
    padding: 6px 12px 8px;
  }

  .usageHeading {
    padding: 4px 12px 1px;
  }
}"""
        if old_details in c:
            c = c.replace(old_details, new_details, 1)
            changed = True
            applied.append("mobile full-width details & z-index 20")

    if changed:
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(c)

    if applied:
        print(f"  [+] Patched trajectory mobile summary & view ({', '.join(applied)}).")
    return True


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
        frame_ok = "const isMobile" in c and "mobileBackdrop" in c
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

    # 8. Android session lease (flock fallback): 0.1.5's write lease takes a
    #    kernel flock through a native addon that throws on android — the
    #    marker-lease fallback in lease.ts is what makes session resume work
    #    on Termux at all. If a merge drops it, EVERY session dies with
    #    "flock is not supported on android-arm64" — so verify loudly.
    lease_path = os.path.join(REPO_DIR, "packages", "session", "session-persistence-jsonl", "src", "lease.ts")
    lease_ok = False
    if os.path.exists(lease_path):
        with open(lease_path, "r", encoding="utf-8") as f:
            c = f.read()
        lease_ok = "useMarkerLease" in c and "ERR_FLOCK_UNSUPPORTED_PLATFORM" in c and "acquireMarker" in c
    print(f"[*] Android Session Lease (no flock):  {'[PASS]' if lease_ok else '[FAIL]'}")

    # 9. Mobile User Questions UI
    qc_path = os.path.join(REPO_DIR, "packages", "client", "ui-user-questions", "src", "client", "QuestionComposer.module.css")
    qc_ok = False
    if os.path.exists(qc_path):
        with open(qc_path, "r", encoding="utf-8") as f:
            c = f.read()
        qc_ok = "padding-left: var(--dsh-composer-side-clearance)" in c and "flex-wrap: wrap" in c
    print(f"[*] Mobile User Questions Clearance:   {'[PASS]' if qc_ok else '[FAIL]'}")

    # 10. Mobile Trajectory Summary
    traj_path = os.path.join(REPO_DIR, "packages", "client", "ui-trajectory", "src", "client", "TrajectoryTable.module.css")
    traj_ok = False
    if os.path.exists(traj_path):
        with open(traj_path, "r", encoding="utf-8") as f:
            c = f.read()
        traj_ok = "isolation: isolate" in c and "z-index: 20" in c and "white-space: normal" in c
    print(f"[*] Mobile Trajectory Summary & View:  {'[PASS]' if traj_ok else '[FAIL]'}")

    print("==================================================")
    all_ok = att_ok and sess_ok and auth_ok and frame_ok and ms_ok and fs_ok and pkg_ok and lease_ok and qc_ok and traj_ok
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
    patch_fs_ext()
    patch_ripgrep()
    patch_settings_mobile()
    patch_llm_pi_ai_gateway()
    patch_user_questions_mobile()
    patch_trajectory_mobile()
    
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
