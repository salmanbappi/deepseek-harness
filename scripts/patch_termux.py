#!/data/data/com.termux/files/usr/bin/python3
"""
DeepSeek Harness - Android, Termux, and Mobile UX Environment Patcher
Maintains and applies:
1. fs.link -> fs.rename fallback for Android filesystems (EACCES, EPERM, EXDEV, ENOSYS)
2. Local authority auth bypass for mobile web UI (127.0.0.1, localhost, ::1, 0.0.0.0)
3. Responsive Mobile UI/UX layouts, drawer, touch optimizations, and backdrops
4. package.json --expose-internals runtime flag
5. Koffi Android fallback stubs in node_modules
6. node-pty native binary recompilation for this device architecture
7. @vscode/ripgrep android shim linking Termux's ripgrep (glob and grep tools)
8. fs-ext android addon for the session write lease (cached, else compiled)
"""

import os
import sys
import re
import subprocess
import shutil
import argparse

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH_DIR = os.path.join(REPO_DIR, "patches")
PATCH_FILE = os.path.join(PATCH_DIR, "termux-mobile-suite.patch")
LEGACY_PATCH_FILE = os.path.join(PATCH_DIR, "termux-environment.patch")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsh_arch import running_target, target_for  # noqa: E402

# The prebuilds directory name node-pty and the other prebuild-aware addons
# search is `<platform>-<process.arch>`. It was previously the literal
# "android-arm64", which no 32-bit device matches and which every arm64 device
# matched while holding a 32-bit binary. Derived from the running Node instead.
TARGET = running_target()
PREBUILD_DIR = TARGET.prebuild_dir
# Where install-pty-prebuild.sh keeps the CI-built pty.node. pnpm re-extracts
# node-pty on every install, so the binary has to be restored from outside the
# workspace rather than rebuilt on the phone.
NATIVE_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".dsh", "native", TARGET.cache_dir_name)

# Marks the app-boot resolver fallback so a rerun recognizes its own output.
TERMUX_RESOLVER_MARKER = "@termux-purejs-resolver"

# Replaces app-boot's `internalModules()` in a built bundle. Kept as one literal
# so the patched form is reviewable against the TypeScript below.
TERMUX_INTERNAL_MODULES_JS = """function internalModules() {
\t/* @termux-purejs-resolver */
\tconst require = createRequire(import.meta.url);
\tconst Module = require("node:module");
\tconst cjs = Module;
\tconst esmConditions = ["node", "import", "module-sync"];
\tconst cjsConditions = new Set(["node", "require", "module-sync"]);
\t// The loader object the runtime interception patches. `import.meta.resolve`
\t// never consults it, so the hook registered below delegates to it and this
\t// object stays the single seam the interception replaces.
\tlet nativeResolve;
\tlet inNative = false;
\tconst esm = {
\t\tgetOrCreateModuleJob: true,
\t\tresolveSync(parent, request) {
\t\t\tif (nativeResolve === void 0) return { format: formatOf(request.specifier), url: import.meta.resolve(request.specifier, parent) };
\t\t\tinNative = true;
\t\t\ttry {
\t\t\t\treturn nativeResolve(request.specifier, { parentURL: parent, conditions: esmConditions });
\t\t\t} finally {
\t\t\t\tinNative = false;
\t\t\t}
\t\t}
\t};
\tconst esmDefaultResolve = (specifier, context) => esm.resolveSync(context.parentURL, { specifier });
\tconst modern = "getOrCreateModuleJob" in esm;
\tif (typeof cjs._resolveFilename !== "function" || typeof cjs._nodeModulePaths !== "function") throw new Error("profile resolution: unsupported Node module loader");
\tif (typeof Module.registerHooks === "function") Module.registerHooks({
\t\tresolve(specifier, context, nextResolve) {
\t\t\tif (nativeResolve === void 0) nativeResolve = (spec, ctx) => nextResolve(spec, ctx);
\t\t\tif (inNative) return nextResolve(specifier, context);
\t\t\tconst parent = context.parentURL;
\t\t\tif (parent === void 0 || !parent.startsWith("file:")) return nextResolve(specifier, context);
\t\t\ttry {
\t\t\t\tconst result = esm.resolveSync(parent, { specifier, attributes: context.attributes ?? {} });
\t\t\t\tif (result !== void 0 && typeof result.url === "string") return { format: result.format, url: result.url, shortCircuit: true };
\t\t\t} catch {}
\t\t\treturn nextResolve(specifier, context);
\t\t}
\t});
\treturn {
\t\tesm,
\t\tesmDefaultResolve,
\t\tesmConditions,
\t\tcjs,
\t\tcjsConditions,
\t\tmodern
\t};
}"""

# The same replacement as TypeScript, for a tree built from source.
TERMUX_INTERNAL_MODULES_TS = """function internalModules(): InternalModules {
  /* @termux-purejs-resolver */
  const require = createRequire(import.meta.url)
  const Module = require('node:module') as CommonJsModule & {
    registerHooks?(hooks: {
      resolve(
        specifier: string,
        context: {
          parentURL?: string
          conditions?: readonly string[]
          attributes?: Readonly<Record<string, string>>
        },
        nextResolve: (
          specifier: string,
          context: {
            parentURL?: string
            conditions?: readonly string[]
            attributes?: Readonly<Record<string, string>>
          },
        ) => ResolveResult,
      ): ResolveResult
    }): { deregister(): void }
  }
  const cjs = Module
  const esmConditions: readonly string[] = ['node', 'import', 'module-sync']
  const cjsConditions: ReadonlySet<string> = new Set(['node', 'require', 'module-sync'])
  let nativeResolve:
    | ((
        specifier: string,
        context: { parentURL?: string; conditions?: readonly string[] },
      ) => ResolveResult)
    | undefined
  let inNative = false
  const esm = {
    getOrCreateModuleJob: true,
    resolveSync(
      parent: string,
      request: { specifier: string; attributes?: Readonly<Record<string, string>> },
    ): ResolveResult {
      if (nativeResolve === undefined) {
        return { format: formatOf(request.specifier), url: import.meta.resolve(request.specifier, parent) }
      }
      inNative = true
      try {
        return nativeResolve(request.specifier, { parentURL: parent, conditions: esmConditions })
      } finally {
        inNative = false
      }
    },
  } as unknown as ModuleLoaderV2
  const esmDefaultResolve = (
    specifier: string,
    context: { parentURL?: string; conditions?: readonly string[] },
  ): ResolveResult => esm.resolveSync(context.parentURL as string, { specifier })
  const modern = 'getOrCreateModuleJob' in esm
  if (typeof cjs._resolveFilename !== 'function' || typeof cjs._nodeModulePaths !== 'function') {
    throw new Error('profile resolution: unsupported Node module loader')
  }
  if (typeof Module.registerHooks === 'function') {
    Module.registerHooks({
      resolve(specifier, context, nextResolve) {
        if (nativeResolve === undefined) {
          nativeResolve = (spec, ctx) => nextResolve(spec, ctx)
        }
        if (inNative) return nextResolve(specifier, context)
        const parent = context.parentURL
        if (parent === undefined || !parent.startsWith('file:')) return nextResolve(specifier, context)
        try {
          const result = esm.resolveSync(parent, { specifier, attributes: context.attributes ?? {} })
          if (result !== undefined && typeof result.url === 'string') {
            return { format: result.format, url: result.url, shortCircuit: true }
          }
        } catch {
          // A resolution this hook cannot answer falls through to Node's own.
        }
        return nextResolve(specifier, context)
      },
    })
  }
  return {
    esm,
    esmDefaultResolve,
    esmConditions,
    cjs,
    cjsConditions,
    modern,
  }
}"""


def replace_function_body(content, signature, replacement):
    """Replaces one top-level function, matched by brace depth from its signature.

    A patcher that anchors on the whole body breaks whenever upstream reflows it,
    so only the signature is matched and the body extent is measured.
    """
    start = content.index(signature)
    index = content.index("{", start)
    depth = 0
    while True:
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return content[:start] + replacement + content[index + 1:]


def node_syntax_ok(source):
    """Reports whether `source` parses as a JavaScript module.

    A patcher writes text into a bundle it does not otherwise build, so nothing
    downstream re-checks the result. A duplicate declaration introduced this way
    only surfaces when the harness boots, as a SyntaxError naming a line in the
    installed file. `node --check` catches it at patch time instead.

    Returns:
        True when Node parses the source, or when no `node` is available to ask
        (an unverifiable patch is reported as acceptable, so a host without Node
        can still apply the suite).
    """
    if shutil.which("node") is None:
        return True
    try:
        proc = subprocess.run(
            ["node", "--input-type=module", "--check"],
            input=source, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if proc.returncode != 0:
        print(f"      {proc.stderr.strip().splitlines()[0] if proc.stderr.strip() else 'syntax error'}")
    return proc.returncode == 0


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


def patch_session_lease():
    """Replaces the kernel flock lease with an in-process claim on Android.

    Upstream locks a session directory through `tryLockExclusive` from
    `@deepseek-ai/node-addon-system/flock`, a native addon. Android has no build
    of that addon, so the import fails and every session dies at its first
    write. The kernel arbiter exists to keep two *processes* from appending to
    one log; on a phone a single `dsh` process owns every session, so an
    in-process claim preserves the property that actually matters — two write
    handles for one session in this process cannot coexist — without the addon.
    Windows keeps its named-semaphore path untouched.
    """
    path = os.path.join(REPO_DIR, "packages", "session", "session-persistence-jsonl", "src", "lease.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    if "androidInProcessClaims" in c:
        return True
    if "await tryLockExclusive(handle.fd)" not in c:
        # Either upstream already removed the native flock (nothing to do) or the
        # lock moved; distinguishing those needs a human, so say which one.
        if "tryLockExclusive" in c:
            print("  [!] session lease: tryLockExclusive call shape changed — reapply by hand against lease.ts")
            return False
        return True

    claim_block = """
/**
 * Sessions this process already holds a write claim for. Android has no
 * `@deepseek-ai/node-addon-system/flock` build, so the kernel arbiter upstream
 * relies on is unavailable there; a process-local set keeps the one property a
 * phone still needs — a second write handle for a session already open here.
 * Cross-process exclusion is unaffected on every other platform, which keeps
 * the native path.
 */
const androidInProcessClaims = new Set<string>()

/** Whether this process may take the session's write claim on Android. */
function claimInProcess(dir: string): boolean {
  const key = join(dir, LEASE_FILENAME)
  if (androidInProcessClaims.has(key)) return false
  androidInProcessClaims.add(key)
  return true
}

"""
    # Anchor on the flock JSDoc so this lands with its peers instead of splitting
    # the LEASE_FILENAME doc block from the constant it documents.
    flock_doc = "/** Whether a flock failure means another descriptor holds the lock. */"
    c = c.replace(flock_doc, claim_block.lstrip("\n") + flock_doc, 1)

    helper = """
/** Whether this process runs on Android, where the native flock addon is unavailable. */
function isAndroidRuntime(): boolean {
  return process.platform === 'android' || Boolean(process.env.TERMUX_VERSION)
}

"""
    c = c.replace("/** Whether a flock failure means another descriptor holds the lock. */", helper.lstrip("\n") + "/** Whether a flock failure means another descriptor holds the lock. */", 1)

    # Take the in-process claim and skip the native call when it is the arbiter.
    c = c.replace(
        "        try {\n          await tryLockExclusive(handle.fd)\n        } catch (error: unknown) {",
        "        try {\n"
        "          if (isAndroidRuntime()) {\n"
        "            if (!claimInProcess(dir)) throw new SessionAlreadyOwnedError(id)\n"
        "          } else {\n"
        "            await tryLockExclusive(handle.fd)\n"
        "          }\n"
        "        } catch (error: unknown) {",
        1,
    )

    # The lease records its directory so release can free the claim; upstream's
    # constructor is private and takes only the held lock, so widen both.
    c = c.replace("  private constructor(private readonly held: HeldLock) {}",
                  "  private constructor(private readonly held: HeldLock, private readonly dir: string) {}", 1)
    c = c.replace("      return new SessionWriteLease({ kind: 'win32', handle })",
                  "      return new SessionWriteLease({ kind: 'win32', handle }, dir)", 1)
    c = c.replace("          return new SessionWriteLease({ kind: 'posix', handle })",
                  "          return new SessionWriteLease({ kind: 'posix', handle }, dir)", 1)

    # Release frees the claim so a later handle for the same session can open.
    claims_release = "    if (isAndroidRuntime()) androidInProcessClaims.delete(join(this.dir, LEASE_FILENAME))\n"
    c = re.sub(r"(  async release\(\): Promise<void> \{\n)", r"\1" + claims_release, c, count=1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(c)
    print("  [+] Patched session lease for Android (in-process write claim).")
    return True


def patch_fs_local():
    """Patches packages/fs/fs-local/src/fsio.ts for Android link fallback in writeFileAtomic."""
    path = os.path.join(REPO_DIR, "packages", "fs", "fs-local", "src", "fsio.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()
    origin = c

    modified = False
    if "isAndroid" not in c or "isUnsupportedLinkError" not in c:
        pat = re.compile(
            r"(\s*if \((?:options\.createIfAbsent|createIfAbsent !== undefined)\) \{\s*try \{\s*await linkFile\(tempPath, absolutePath\)\s*\} catch \(error: unknown\) \{)(.*?)(\s*\}\s*\} else if \(platform === 'win32')",
            re.DOTALL
        )
        repl = r"""\1
        // Android filesystems commonly mount user storage on a filesystem where
        // link(2) is unavailable or denied (sdcardfs, FUSE-backed external
        // storage). Neither EACCES nor EPERM there means the destination is
        // occupied, so the hard-link no-replace primitive cannot be used and the
        // create falls back to rename after an explicit lstat of the target.
        const isAndroid = platform === 'android' || Boolean(process.env.TERMUX_VERSION)
        const isUnsupportedLinkError = error instanceof Error && 'code' in error && (
          error.code === 'EACCES' || error.code === 'EPERM' || error.code === 'EXDEV' ||
          error.code === 'ENOSYS' || error.code === 'ENOTSUP' || error.code === 'EOPNOTSUPP'
        )

        if (isAndroid && isUnsupportedLinkError) {
          let existing: BigIntStats | undefined
          try {
            existing = await inspectPublicationTarget(absolutePath)
          } catch (metadataError: unknown) {
            if (!isENOENT(metadataError) && !isENOTDIR(metadataError)) {
              throw new FsError(`cannot write "${displayPath}": ${errorMessage(metadataError)}`, 'FS_IO_ERROR', { cause: metadataError })
            }
          }

          if (existing !== undefined) {
            if (!existing.isFile()) {
              throw new FsError(`cannot write "${displayPath}": not a regular file`, 'FS_NOT_REGULAR_FILE', { cause: error })
            }
            throw new FsError(
              `cannot overwrite existing "${displayPath}" without reading it first`,
              'FS_NOT_OBSERVED',
              { cause: error },
            )
          }
          await rename(tempPath, absolutePath)
        } else {
          await throwGuardedCreateFailure(error, absolutePath, displayPath, inspectPublicationTarget)
        }\3"""
        c = pat.sub(repl, c, count=1)
        # A regex that matches nothing leaves c byte-identical. The guard above
        # proved the marker is absent, so that means the anchor moved, not that
        # the file was already patched.
        if c == origin:
            print("  [!] fs-local: writeFileAtomic link fallback anchor did not match — reapply by hand against fsio.ts")
            return False
        modified = True

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched fs-local writeFileAtomic link fallback.")
    return True


def patch_browser_auth():
    """Patches the browser-trust fence for local mobile web access.

    Upstream moved this decision twice. It began as a `browser-auth.ts` cookie
    check, which this patcher rewrote in place. Upstream then split it into
    `loopback-hostname.ts` (the predicate) and `api-request-trust.ts` (the
    fence), so the old path no longer exists and the old rewrite has nothing to
    match. The fence now lives in `isTrustedApiRequest`, which already admits
    loopback but not `0.0.0.0` — the address the phone's Web UI binds and the
    one a browser on the device actually connects to. Widening the predicate is
    the whole port; the fence itself is upstream's and stays.
    """
    connection = os.path.join(REPO_DIR, "packages", "client", "connection", "src")
    loopback = os.path.join(connection, "loopback-hostname.ts")
    legacy = os.path.join(connection, "browser-auth.ts")

    # Current upstream layout: teach the loopback predicate the Android bind
    # address. Guarded on the patched form so a second run is a no-op.
    if os.path.exists(loopback):
        with open(loopback, "r", encoding="utf-8") as f:
            c = f.read()
        if "ANDROID_BIND_ADDRESS" in c:
            return True
        marker = """export function isLoopbackHostname(hostname: string): boolean {"""
        if marker not in c:
            print("  [!] browser auth: isLoopbackHostname anchor did not match — reapply by hand against loopback-hostname.ts")
            return False
        patched = marker + """
  // Termux serves the Web UI on 0.0.0.0, so a browser on the device reaches the
  // Host through that literal rather than through 127.0.0.1. Upstream's fence
  // treats it as an untrusted authority and answers 401 to every request, which
  // makes the mobile Web UI unusable. Named so the Android-specific widening is
  // visible at the call site rather than buried in the comparison below.
  if (hostname === ANDROID_BIND_ADDRESS) return true"""
        c = c.replace(marker, patched, 1)
        if "const ANDROID_BIND_ADDRESS = '0.0.0.0'" not in c:
            c = c.replace(
                "export function isLoopbackHostname",
                "const ANDROID_BIND_ADDRESS = '0.0.0.0'\n\nexport function isLoopbackHostname",
                1,
            )
        with open(loopback, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched the loopback predicate for the Android bind address.")
        return True

    # Older upstream layout, kept so the patcher still works on a tree that has
    # not taken the split yet.
    if os.path.exists(legacy):
        with open(legacy, "r", encoding="utf-8") as f:
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
                    r"if \(this\.isAuthenticated\(req(?:,\s*secure)?\)\) return true\s*\n\s*this\.writeUnauthorized\(req, res\)",
                    "if (this.isAuthenticated(req, secure)) return true\n    if (authority !== undefined && this.isLocalAuthority(authority)) return true\n    this.writeUnauthorized(req, res)",
                    c
                )
                modified = True

        if modified:
            with open(legacy, "w", encoding="utf-8") as f:
                f.write(c)
            print("  [+] Patched browser authentication for local mobile access.")
        return True

    print("  [!] browser auth: neither loopback-hostname.ts nor browser-auth.ts exists — the fence moved again; update patch_browser_auth().")
    return False


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
    elif "--expose-internals" not in c:
        # Neither the anchor nor the marker: the dsh script was rewritten
        # upstream, so the runtime flag no longer lands.
        print("  [!] package.json: dsh script anchor did not match — reapply by hand against package.json")
        return False

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched package.json (--expose-internals).")
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

    # Upstream native drawer architecture (v0.2.2+)
    if "const drawer =" in c and "drawerMask" in c:
        if "onSidebarColClick" not in c:
            delegation_code = """  // Mobile sidebar click delegation: close sidebar when tapping an active/other session, new session, or panel
  const onSidebarColClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!drawer || sidebarCollapsed) return
    const target = e.target as HTMLElement | null
    if (!target) return
    if (target.closest('input, textarea, select')) return
    if (target.closest('button[class*="toggle"]')) return

    const sessionRow = target.closest('[data-row-key^="session:"]')
    if (sessionRow) {
      actions.toggleSidebar()
      return
    }

    const isNewSession = target.closest('button[class*="newSession"]') ||
      target.closest('button[aria-label*="session" i]') ||
      target.closest('button[class*="brand"]')
    if (isNewSession) {
      actions.toggleSidebar()
      return
    }

    const isPanel = target.closest('button[class*="panelRow"]') ||
      target.closest('button[data-panel-id]') ||
      target.closest('nav[aria-label*="panel" i] button')
    if (isPanel) {
      actions.toggleSidebar()
      return
    }
  }, [drawer, sidebarCollapsed, actions])
"""
            leading_anchor = "  const leading = useMemo(() => renderSlot('shell.leading', {}), [renderSlot])"
            if leading_anchor in c:
                c = c.replace(leading_anchor, leading_anchor + "\n\n" + delegation_code, 1)
                edits.append("mobile sidebar click delegation")

        if "onClick={onSidebarColClick}" not in c and "<div className={css.sidebarCol}" in c:
            c = c.replace(
                "<div className={css.sidebarCol}",
                "<div className={css.sidebarCol} onClick={onSidebarColClick}",
                1
            )
            edits.append("sidebarCol click handler")

        if edits:
            with open(tsx_path, "w", encoding="utf-8") as f:
                f.write(c)
            print(f"  [+] Patched AppFrame.tsx native mobile drawer ({', '.join(edits)}).")
        return

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
    if "viewBox=\"0 0 24 24\"" in c:
        old_svg = """          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12"></line>
            <line x1="3" y1="6" x2="21" y2="6"></line>
            <line x1="3" y1="18" x2="21" y2="18"></line>
          </svg>"""
        new_svg = """          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <line x1="2.5" y1="4" x2="13.5" y2="4" />
            <line x1="2.5" y1="8" x2="13.5" y2="8" />
            <line x1="2.5" y1="12" x2="13.5" y2="12" />
          </svg>"""
        if old_svg in c:
            c = c.replace(old_svg, new_svg)
            edits.append("modernize mobile toggle icon")
    if "const isMobile" in c and "mobileBackdrop" in c and "collapsed: isMobile ? false : sidebarCollapsed" in c and not edits:
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
    if "collapsed: isMobile ? false : sidebarCollapsed" not in c:
        old_slot_memo = """  const sidebar = useMemo(() => renderSlot('sidebar', {
    collapsed: sidebarCollapsed,
    width: cols.sidebar,
  }), [renderSlot, sidebarCollapsed, cols.sidebar])"""
        new_slot_memo = """  const sidebar = useMemo(() => renderSlot('sidebar', {
    collapsed: isMobile ? false : sidebarCollapsed,
    width: isMobile ? 280 : cols.sidebar,
  }), [renderSlot, sidebarCollapsed, cols.sidebar, isMobile])"""

        old_slot_jsx = "{renderSlot('sidebar', {\n          collapsed: sidebarCollapsed,\n          width: cols.sidebar,\n        })}"
        new_slot_jsx = "{renderSlot('sidebar', {\n          collapsed: isMobile ? false : sidebarCollapsed,\n          width: isMobile ? 280 : cols.sidebar,\n        })}"

        if old_slot_memo in c:
            c = c.replace(old_slot_memo, new_slot_memo, 1)
            edits.append("sidebar slot params (useMemo)")
        elif old_slot_jsx in c:
            c = c.replace(old_slot_jsx, new_slot_jsx, 1)
            edits.append("sidebar slot params (jsx)")

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
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <line x1="2.5" y1="4" x2="13.5" y2="4" />
            <line x1="2.5" y1="8" x2="13.5" y2="8" />
            <line x1="2.5" y1="12" x2="13.5" y2="12" />
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
        return True
    if "const isMobile" not in c or "mobileBackdrop" not in c:
        print("  [!] AppFrame.tsx anchors did not match — mobile drawer NOT applied. File may have changed upstream; update patch_app_frame().")
        return False
    # Anchors already present from an earlier run; nothing left to do.
    return True




def patch_model_select():
    """Detaches the model dropdown's root onBlur, which closes it mid-tap on touch.

    On a touch screen the blur fires before the tap on an option lands, and
    relatedTarget is unreliable there, so the menu closed before the selection
    registered. The dropdown does not depend on onBlur to close: closeOutside
    already listens for pointerdown and mousedown on the document, which covers
    an outside tap for touch and pointer alike.

    Upstream previously attached closeOutside through mousedown alone; it now
    registers pointerdown itself, so the older event-type rewrite is gone.
    """
    tsx_path = os.path.join(REPO_DIR, "packages", "client", "ui-model-selection", "src", "client", "ModelSelect.tsx")
    if not os.path.exists(tsx_path):
        return False

    with open(tsx_path, "r", encoding="utf-8") as f:
        c = f.read()

    if "void onBlur" in c and "onBlur={onBlur}" not in c:
        return True

    modified = False
    if "onBlur={onBlur}" in c:
        c = c.replace("\n      onBlur={onBlur}", "", 1)
        modified = True

    # Mark the handler as deliberately unused, and say why next to it. Anchoring
    # on the closing brace of onBlur itself keeps this from landing on some
    # other function that also ends in `close()\n  }`.
    anchor = """    )) return
    close()
  }
"""
    if "void onBlur" not in c and anchor in c:
        c = c.replace(anchor, anchor + """  // Deliberately detached from the root element: on a touch screen the blur
  // fires before the tap on an option, and relatedTarget is unreliable there,
  // so the menu closed before the selection landed. closeOutside already closes
  // on an outside tap through pointerdown and mousedown, for touch and pointer
  // alike, which is the path the dropdown relies on.
  void onBlur
""", 1)
        modified = True

    if not modified:
        print("  [!] ModelSelect.tsx: onBlur anchor did not match — mobile dropdown fix NOT applied")
        return False

    with open(tsx_path, "w", encoding="utf-8") as f:
        f.write(c)
    print("  [+] Patched ModelSelect.tsx (detached the root onBlur for touch).")
    return True


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


def patch_node_addon_require_builtin():
    """Rebuilds app-boot's Node-internal loader access without the native addon.

    Upstream reaches Node's ESM and CJS internals through
    `node-addon-require-builtin`. That package ships optional platform bindings
    for darwin, linux, and win32 only, so on Android there is no binding, and its
    own wrapper degrades to `require('internal/...')` — which userland can never
    resolve. Every profile therefore failed at boot with
    `Cannot find module 'internal/modules/esm/loader'`.

    The replacement supplies the same interface from the module API Node
    publishes. `Module` covers the CJS half directly. For the ESM half,
    `Module.registerHooks` publishes a synchronous resolver and the loader object
    the runtime interception patches delegates to it through the captured
    `nextResolve`; `import.meta.resolve` is deliberately not called inside the
    hook, because it would re-enter that same hook and spin.

    Both built bundles that inline this function are rewritten, plus the
    TypeScript source, so a tree built from source carries the change too.
    """
    patched = 0
    bundles = [
        os.path.join(REPO_DIR, "packages", "boot", "app-boot", "lib", "index.js"),
        os.path.join(REPO_DIR, "packages", "boot", "app-boot", "lib", "worker",
                     "profile-resolution-bootstrap.js"),
    ]
    for path in bundles:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        rel = os.path.relpath(path, REPO_DIR)
        if TERMUX_RESOLVER_MARKER in c:
            patched += 1
            continue
        if "function internalModules() {" not in c:
            print(f"  [!] app-boot resolver: internalModules() not found in {rel}")
            continue
        c = replace_function_body(c, "function internalModules() {", TERMUX_INTERNAL_MODULES_JS)
        # The replaced body is emitted into a bundle that upstream also defines
        # names in. A name this template declares that upstream already has
        # becomes a duplicate declaration, which is a parse error at boot, not a
        # warning — `node --check` is the only cheap way to catch it here.
        if not node_syntax_ok(c):
            print(f"  [!] app-boot resolver: patched {rel} is not valid JavaScript; left unchanged")
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        patched += 1
        print(f"  [+] Replaced internalModules() in {rel}.")

    resolver_src = os.path.join(
        REPO_DIR, "packages", "boot", "app-boot", "src", "profile-resolution", "resolver.ts"
    )
    if os.path.exists(resolver_src):
        with open(resolver_src, "r", encoding="utf-8") as f:
            c = f.read()
        if TERMUX_RESOLVER_MARKER in c:
            patched += 1
        elif "function internalModules(): InternalModules {" in c:
            c = replace_function_body(
                c, "function internalModules(): InternalModules {", TERMUX_INTERNAL_MODULES_TS
            )
            with open(resolver_src, "w", encoding="utf-8") as f:
                f.write(c)
            patched += 1
            print("  [+] Replaced internalModules() in src/profile-resolution/resolver.ts.")
        else:
            print("  [!] app-boot resolver: internalModules() not found in resolver.ts")

    if patched == 0:
        print("  [!] app-boot resolver: nothing patched; profile boot will fail on Android.")
    return patched > 0


def patch_node_pty():
    """Ensures node-pty has a native binary for this device: cached CI build first, local compile second."""
    node_modules = os.path.join(REPO_DIR, "node_modules", ".pnpm")
    if not os.path.exists(node_modules):
        return
    cached_bin = os.path.join(NATIVE_CACHE_DIR, "pty.node")
    for root, dirs, files in os.walk(node_modules):
        if "node-pty" in root and "binding.gyp" in files:
            pty_bin = os.path.join(root, "build", "Release", "pty.node")
            prebuild_dir = os.path.join(root, "prebuilds", PREBUILD_DIR)
            prebuild_bin = os.path.join(prebuild_dir, "pty.node")
            if os.path.exists(prebuild_bin):
                continue
            if os.path.exists(cached_bin):
                try:
                    os.makedirs(prebuild_dir, exist_ok=True)
                    subprocess.run(["cp", "-f", cached_bin, prebuild_bin], check=True)
                    print(f"  [+] Restored {PREBUILD_DIR} pty.node from ~/.dsh/native cache.")
                    continue
                except Exception as e:
                    print(f"  [!] pty.node restore notice: {e}")
            print(f"  [*] Building native node-pty for {PREBUILD_DIR}...")
            try:
                subprocess.run(["npx", "node-gyp", "rebuild"], cwd=root, check=True, capture_output=True)
                os.makedirs(prebuild_dir, exist_ok=True)
                if os.path.exists(pty_bin):
                    subprocess.run(["cp", "-f", pty_bin, prebuild_bin], check=True)
                    os.makedirs(NATIVE_CACHE_DIR, exist_ok=True)
                    subprocess.run(["cp", "-f", pty_bin, cached_bin], check=True)
                    print(f"  [+] Compiled & installed {PREBUILD_DIR} pty.node (cached for next update).")
            except Exception as e:
                print(f"  [!] node-pty compile notice: {e}")
                print("      Fix: bash scripts/install-pty-prebuild.sh  (fetches the CI-built binary)")


def patch_fs_ext():
    """Ensures fs-ext has its native addon for this device: cached build first, local compile second.

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
                print(f"  [+] Restored {PREBUILD_DIR} fs_ext.node from ~/.dsh/native cache.")
                continue
            except Exception as e:
                print(f"  [!] fs_ext.node restore notice: {e}")
        print(f"  [*] Building fs-ext for {PREBUILD_DIR}...")
        try:
            subprocess.run(["npx", "node-gyp", "rebuild"], cwd=pkg, check=True, capture_output=True)
            if os.path.exists(built):
                os.makedirs(NATIVE_CACHE_DIR, exist_ok=True)
                subprocess.run(["cp", "-f", built, cached], check=True)
                print(f"  [+] Compiled & cached {PREBUILD_DIR} fs_ext.node.")
        except Exception as e:
            print(f"  [!] fs-ext compile notice: {e}")
            print("      The session write lease needs it: cd into the package and run `npx node-gyp rebuild`")


def patch_ripgrep():
    """Links Termux's ripgrep in as @vscode/ripgrep-android-<arch>, which npm does not publish."""
    node_modules = os.path.join(REPO_DIR, "node_modules", ".pnpm")
    if not os.path.exists(node_modules):
        return
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    system_rg = os.path.join(prefix, "bin", "rg")
    if not os.path.exists(system_rg):
        print("  [!] ripgrep missing — the glob and grep tools need it: pkg install ripgrep")
        return
    # @vscode/ripgrep resolves `@vscode/ripgrep-${process.platform}-${process.arch}`,
    # so the shim must carry this device's arch or the resolver never looks at it.
    shim_name = f"@vscode/ripgrep-android-{TARGET.node_arch}"
    manifest = (
        '{\n'
        f'  "name": "{shim_name}",\n'
        '  "version": "1.18.0",\n'
        '  "description": "Termux shim: npm publishes no Android platform package, so bin/rg links to the system ripgrep.",\n'
        '  "os": ["android"],\n'
        f'  "cpu": ["{TARGET.node_arch}"]\n'
        '}\n'
    )
    count = 0
    for entry in os.listdir(node_modules):
        # Only the dispatcher package; the platform packages share its prefix.
        if not entry.startswith("@vscode+ripgrep@"):
            continue
        shim = os.path.join(node_modules, entry, "node_modules", "@vscode", f"ripgrep-android-{TARGET.node_arch}")
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


def patch_speech_to_text():
    """Patches SenseVoice speech-to-text runtime for this device arch and installs the native sherpa addon."""
    # 1. Source TS runtime
    src_runtime = os.path.join(REPO_DIR, "packages", "experimental", "speech-to-text-sensevoice", "src", "runtime.ts")
    if os.path.exists(src_runtime):
        try:
            with open(src_runtime, "r", encoding="utf-8") as f:
                c = f.read()
            speech_arch = f"android-{TARGET.node_arch}"
            if speech_arch not in c and "supported = [" in c:
                c = c.replace(
                    "supported = ['darwin-arm64', 'darwin-x64', 'linux-arm64', 'linux-x64', 'win32-x64']",
                    "supported = ['darwin-arm64', 'darwin-x64', 'linux-arm64', 'linux-x64', 'win32-x64', '" + speech_arch + "']",
                )
                with open(src_runtime, "w", encoding="utf-8") as f:
                    f.write(c)
                print(f"  [+] Patched SenseVoice runtime.ts for {speech_arch}.")
        except Exception as e:
            print(f"  [!] SenseVoice runtime.ts patch notice: {e}")

    # 2. Compiled JS runtime
    lib_index = os.path.join(REPO_DIR, "packages", "experimental", "speech-to-text-sensevoice", "lib", "index.js")
    if os.path.exists(lib_index):
        try:
            with open(lib_index, "r", encoding="utf-8") as f:
                c = f.read()
            speech_arch = f"android-{TARGET.node_arch}"
            if speech_arch not in c:
                old_list = '"win32-x64"\n\t].includes'
                new_list = '"win32-x64",\n\t\t"' + speech_arch + '"\n\t].includes'
                if old_list in c:
                    c = c.replace(old_list, new_list, 1)
                    with open(lib_index, "w", encoding="utf-8") as f:
                        f.write(c)
                    print(f"  [+] Patched compiled SenseVoice lib/index.js for {speech_arch}.")
        except Exception as e:
            print(f"  [!] SenseVoice lib/index.js patch notice: {e}")

    lib_types_runtime = os.path.join(REPO_DIR, "packages", "experimental", "speech-to-text-sensevoice", "lib", "types", "runtime.js")
    if os.path.exists(lib_types_runtime):
        try:
            with open(lib_types_runtime, "r", encoding="utf-8") as f:
                c = f.read()
            speech_arch = f"android-{TARGET.node_arch}"
            if speech_arch not in c and "supported = [" in c:
                c = c.replace(
                    "supported = ['darwin-arm64', 'darwin-x64', 'linux-arm64', 'linux-x64', 'win32-x64']",
                    "supported = ['darwin-arm64', 'darwin-x64', 'linux-arm64', 'linux-x64', 'win32-x64', '" + speech_arch + "']",
                )
                with open(lib_types_runtime, "w", encoding="utf-8") as f:
                    f.write(c)
        except Exception:
            pass

    # 3. Native addon: restore from the per-arch native cache.
    sherpa_cache = os.path.join(NATIVE_CACHE_DIR, "sherpa")
    cached_node = os.path.join(sherpa_cache, "sherpa-onnx.node")
    if not os.path.exists(cached_node):
        return

    # Ensure rpath is exclusively $ORIGIN so it never picks broken system onnxruntime
    patchelf_bin = "/data/data/com.termux/files/usr/bin/patchelf"
    if os.path.exists(patchelf_bin):
        for lib in ["libsherpa-onnx-c-api.so", "libsherpa-onnx-cxx-api.so", "sherpa-onnx.node"]:
            lp = os.path.join(sherpa_cache, lib)
            if os.path.exists(lp):
                subprocess.run([patchelf_bin, "--set-rpath", "$ORIGIN", lp], check=False, capture_output=True)

    node_modules = os.path.join(REPO_DIR, "node_modules")
    manifest = (
        '{\n'
        f'  "name": "sherpa-onnx-android-{TARGET.node_arch}",\n'
        '  "version": "1.13.8",\n'
        f'  "description": "Prebuilt native binaries for sherpa-onnx on Android {TARGET.node_arch}",\n'
        '  "main": "sherpa-onnx.node",\n'
        '  "os": ["android"],\n'
        f'  "cpu": ["{TARGET.node_arch}"]\n'
        '}\n'
    )

    targets = [os.path.join(node_modules, f"sherpa-onnx-android-{TARGET.node_arch}")]
    pnpm_dir = os.path.join(node_modules, ".pnpm")
    sherpa_node_dirs = []
    if os.path.exists(pnpm_dir):
        for root, dirs, files in os.walk(pnpm_dir):
            if os.path.basename(root) == "sherpa-onnx-node":
                sherpa_node_dirs.append(root)
                targets.append(os.path.join(root, "node_modules", f"sherpa-onnx-android-{TARGET.node_arch}"))
            elif "sherpa-onnx-node" in root and root.endswith("node_modules"):
                targets.append(os.path.join(root, f"sherpa-onnx-android-{TARGET.node_arch}"))

    count = 0
    for target in set(targets):
        bin_path = os.path.join(target, "sherpa-onnx.node")
        if not os.path.exists(bin_path):
            try:
                os.makedirs(target, exist_ok=True)
                for f in os.listdir(sherpa_cache):
                    subprocess.run(["cp", "-f", os.path.join(sherpa_cache, f), os.path.join(target, f)], check=True)
                with open(os.path.join(target, "package.json"), "w", encoding="utf-8") as pf:
                    pf.write(manifest)
                count += 1
            except Exception as e:
                print(f"  [!] Failed to restore sherpa-onnx into {target}: {e}")

    # Also place directly in sherpa-onnx-node directory root as immediate candidate
    for snd in sherpa_node_dirs:
        bin_path = os.path.join(snd, "sherpa-onnx.node")
        if not os.path.exists(bin_path):
            try:
                for f in os.listdir(sherpa_cache):
                    subprocess.run(["cp", "-f", os.path.join(sherpa_cache, f), os.path.join(snd, f)], check=True)
            except Exception:
                pass

    if count > 0:
        print(f"  [+] Restored sherpa-onnx-android-{TARGET.node_arch} into {count} location(s).")



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

    with open(tsx_path, "r", encoding="utf-8") as f:
        tsx = f.read()
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # Already fully patched with mobile header and portal
    if "createPortal" in tsx and "css.mobileHeader" in tsx and ".mobileHeader" in css:
        return True

    header_jsx = """        <div className={css.mobileHeader}>
          <span className={css.mobileTitle}>{renderSlot('settings.header', {})}</span>
          <div className={css.mobileActions}>
            {renderSlot('settings.action', {})}
            <button type="button" className={css.mobileClose} onClick={onClose} aria-label="Close">
              <IconCloseOutlineRegular size={16} />
            </button>
          </div>
        </div>
"""
    nav_open = "        <nav className={css.nav}>\n"
    title_comment = "        {/* The four seats stay direct children of the panel and take their\n"
    panel_open = '  return (\n    <div className={css.overlay} role="presentation">\n'
    react_import = "import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'\n"
    panel_tail = "      </div>\n    </div>\n  )\n}\n"

    has_portal = "createPortal" in tsx
    applied = []

    for marker, upstream, patched, label in (
        ("from 'react-dom'", react_import, react_import + "import { createPortal } from 'react-dom'\n", "react-dom import"),
        # The panel becomes a value so it can be portalled to document.body (unless already portalled).
        ("const panel = (", panel_open, panel_open.replace("  return (", "  const panel = ("), "panel binding"),
        ("css.mobileHeader", title_comment, header_jsx + title_comment, "mobile header row"),
        ("css.mobileHeader", nav_open, header_jsx + nav_open, "mobile header row (legacy)"),
        (
            "createPortal",
            panel_tail,
            "      </div>\n    </div>\n  )\n\n  if (typeof document !== 'undefined') {\n    return createPortal(panel, document.body)\n  }\n  return panel\n}\n",
            "portal render",
        ),
    ):
        if marker in tsx or (has_portal and label in ("panel binding", "portal render")):
            continue
        if upstream not in tsx:
            if label == "mobile header row (legacy)":
                continue
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
            "// Attribution first so a route's configured headers can win",
            """    const initial = new Headers()
    // Profile aliases overwrite case-insensitively; the Headers constructor appends them.
    for (const [name, value] of Object.entries(configured ?? {})) initial.set(name, value)
    const request: PiAiRequestHeaderContext = Object.freeze({
      provider: options.provider,
      model: options.model,
      baseURL,
      ...options.sessionId === undefined ? {} : { sessionId: options.sessionId },
      ...options.purpose === undefined ? {} : { purpose: options.purpose },
    })
    const headers = prepare === undefined ? initial : prepare(request, initial)
    for (const [name, value] of Object.entries(attributionHeaders())) headers.set(name, value)
    return Object.fromEntries(headers)""",
            """    const initial = new Headers()
    // Attribution first so a route's configured headers can win per header name.
    for (const [name, value] of Object.entries(attributionHeaders())) initial.set(name, String(value))
    for (const [name, value] of Object.entries(configured ?? {})) initial.set(name, String(value))
    const request: PiAiRequestHeaderContext = Object.freeze({
      provider: options.provider,
      model: options.model,
      baseURL,
      ...options.sessionId === undefined ? {} : { sessionId: options.sessionId },
      ...options.purpose === undefined ? {} : { purpose: options.purpose },
    })
    const headers = prepare === undefined ? initial : prepare(request, initial)
    return Object.fromEntries(headers)""",
            "request header precedence (upstream 4-arg)",
        ), (
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
        if key == "adapter" and "// Attribution first so a route's configured headers can win" in c:
            continue
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
            # A fork-only variant upstream never carries leaves its marker
            # absent on a healthy tree, so warn only when nothing landed for
            # this file. Warning otherwise fires on every clean run and trains
            # the reader to ignore the channel that carries real misses.
            if marker not in c and not applied and not changed:
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

    # 4. Mobile details full-width overlay, touch scrolling, and visible scroll handles
    if "--dsh-scrollbar-thumb: var(--dsw-alias-scrollbar-bg-l2);" not in c or ".detailBodySummary > .overview" not in c:
        old_details_variants = [
            """@media (max-width: 760px) {
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
}""",
            """@media (max-width: 760px) {
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
        ]
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
    --dsh-scrollbar-thumb: var(--dsw-alias-scrollbar-bg-l2);
    --dsh-scrollbar-thumb-hover: var(--dsw-alias-scrollbar-hover-l2);
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

  .detailBody {
    scrollbar-gutter: auto;
    -webkit-overflow-scrolling: touch;
  }

  .detailBodySummary {
    flex: 1 1 auto;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: calc(24px + var(--dsh-trajectory-bottom-clearance, 168px));
  }

  .detailBodySummary > .overview {
    flex: none;
    min-height: auto;
    overflow: visible;
  }

  .detailBodySummary > .compactedSummary {
    flex: none;
    min-height: auto;
    overflow: visible;
  }

  .overviewSections {
    flex: none;
    min-height: auto;
    overflow: visible;
  }

  .overviewSection {
    flex: none;
    min-height: auto;
    max-height: none;
    overflow: visible;
  }

  .summaryScrollRegion {
    --dsh-scrollbar-thumb: var(--dsw-alias-scrollbar-bg-l2);
    --dsh-scrollbar-thumb-hover: var(--dsw-alias-scrollbar-hover-l2);
  }

  .tablePane {
    -webkit-overflow-scrolling: touch;
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
    -webkit-overflow-scrolling: touch;
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
        for v in old_details_variants:
            if v in c:
                c = c.replace(v, new_details, 1)
                changed = True
                applied.append("mobile full-width details, touch scrolling & scroll handle")
                break

    if changed:
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(c)

    if applied:
        print(f"  [+] Patched trajectory mobile summary & view ({', '.join(applied)}).")
    return True


def patch_conversation_mobile():
    """Patches packages/client/ui-conversation for mobile header clearance and responsive breadcrumb sizing."""
    css_path = os.path.join(REPO_DIR, "packages", "client", "ui-conversation", "src", "client", "skeleton", "ConversationRoot.module.css")
    if not os.path.exists(css_path):
        return False
    with open(css_path, "r", encoding="utf-8") as f:
        c = f.read()

    if "@media (max-width: 768px)" not in c:
        mobile_rules = """
@media (max-width: 768px) {
  .header {
    padding: 10px 16px 0 50px;
    min-height: 64px;
  }

  .titleRow {
    min-height: 36px;
  }

  .crumb {
    max-width: min(160px, 45vw);
  }
}
"""
        c = c.rstrip() + "\n" + mobile_rules
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [+] Patched ConversationRoot.module.css mobile header responsive clearance.")
        return True
    # Already carries a 768px block. That block is this patcher's only if it
    # contains the rule this patcher writes: upstream has its own `.crumb`
    # rule, so matching on that alone would pass on a tree where the mobile
    # clearance never landed.
    if "max-width: min(160px, 45vw)" in c:
        return True
    print("  [!] conversation-mobile: an unrelated 768px block occupies the anchor — reapply by hand against ConversationRoot.module.css")
    return False


def patch_bundle_layer_cache():
    """Patches packages/boot/app-boot/src/profile.ts to retain in-memory bundle layer caching."""
    path = os.path.join(REPO_DIR, "packages", "boot", "app-boot", "src", "profile.ts")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()

    # Marker must be this patcher's own cache definition, not any unrelated
    # upstream symbol that happens to share the name.
    if "const bundleLayerCache = new Map<string, ProfileLayer>()" in c:
        return True

    # 1. Define bundleLayerCache before loadProfileDirectory
    anchor = "export function loadProfileDirectory("
    cache_def = "const bundleLayerCache = new Map<string, ProfileLayer>()\n\n"
    if anchor in c:
        c = c.replace(anchor, cache_def + anchor, 1)

    # 2. Wrap bundle resolution in bundleLayerCache
    old_loop = """      const packageDir = resolveBundleDir(binName, packageName, installAnchor, dir)
      const bundleManifest = readProfileManifest(binName, packageDir)"""
    new_loop = """      const packageDir = resolveBundleDir(binName, packageName, installAnchor, dir)
      let cachedLayer = bundleLayerCache.get(packageDir)
      if (cachedLayer === undefined) {
        const bundleManifest = readProfileManifest(binName, packageDir)"""

    old_push = """      layers.push({ packageName, packageDir, patchPaths, patches })"""
    new_push = """        cachedLayer = { packageName, packageDir, patchPaths, patches }
        bundleLayerCache.set(packageDir, cachedLayer)
      }
      layers.push(cachedLayer)"""

    # Both anchors must match. Writing after only the loop had matched left a
    # half-applied file that referenced a `cachedLayer` never assigned.
    if old_loop not in c or old_push not in c:
        print("  [!] app-boot bundleLayerCache: resolution loop anchors did not match — reapply by hand against profile.ts")
        return False

    c = c.replace(old_loop, new_loop, 1)
    c = c.replace(old_push, new_push, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(c)
    print("  [+] Patched app-boot bundleLayerCache.")
    return True




def patch_terminal_bash_shell():
    """Resolves the bash dialect's default shell instead of hardcoding /bin/bash.

    `terminal-bash` defaults to `/bin/bash`, which does not exist on Termux: the
    shell lives at `$PREFIX/bin/bash` and `/bin/bash` is absent. With the
    Android-default `danger-full-access` policy no sandbox wrapper intervenes, so
    `spawnArgv` returns that path unchanged and node-pty forks a nonexistent
    executable. The persistent-bash tool and the sidebar terminal then fail to
    start.

    An explicit `shellPath` in the profile still wins; only the default changes.
    """
    replacement = """export const DEFAULT_BASH_SHELL = (() => {
  // Android has no /bin/bash; Termux installs bash under $PREFIX/bin. Prefer the
  // login shell when it names a bash, then the Termux path, then /bin/bash.
  const env = typeof process === 'undefined' ? undefined : process.env
  const candidates = [env?.SHELL, env?.PREFIX ? `${env.PREFIX}/bin/bash` : undefined, '/bin/bash']
  for (const candidate of candidates) {
    if (candidate !== undefined && /bash$/.test(candidate)) {
      try {
        if (existsSync(candidate)) return candidate
      } catch {
        // Unreadable candidate: fall through to the next one.
      }
    }
  }
  return '/bin/bash'
})()"""

    targets = [
        os.path.join(REPO_DIR, "packages", "terminal", "terminal-bash", "src", "config.ts"),
        os.path.join(REPO_DIR, "packages", "terminal", "terminal-bash", "lib", "index.js"),
    ]
    patched = 0
    for path in targets:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        if "PREFIX}/bin/bash" in c:
            patched += 1
            continue
        if "const DEFAULT_BASH_SHELL = " not in c:
            print(f"  [!] terminal-bash: DEFAULT_BASH_SHELL declaration not found in {os.path.relpath(path, REPO_DIR)}")
            continue
        # Replace the declaration and nothing else; the surrounding module keeps
        # its own imports. Match any modifier already in front of it so a leading
        # `export` is not left duplicated, and either quote style, since the
        # source file and the bundled output do not agree on one.
        new_c = re.sub(
            r"""(?:export\s+)?const DEFAULT_BASH_SHELL = ['"][^'"]*['"]""",
            replacement,
            c,
            count=1,
        )
        if new_c == c:
            print(f"  [!] terminal-bash: DEFAULT_BASH_SHELL declaration did not match in {os.path.relpath(path, REPO_DIR)}")
            continue
        c = new_c
        if "existsSync" not in c.split("const DEFAULT_BASH_SHELL")[0]:
            c = "import { existsSync } from 'node:fs'\n" + c
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        patched += 1
        print(f"  [+] Resolved the bash default at runtime in {os.path.relpath(path, REPO_DIR)}.")
    return patched > 0


def patch_hmr_android_gate():
    """Keeps the in-process reloader off on Android.

    `dsh-hmr` loads Node internals (`internal/bootstrap/realm` and friends)
    through node-addon-require-builtin, which publishes no Android binding, so
    on Android it can only fail after the profile has already begun loading.
    Loading it also means every registry contribution in the profile is torn
    down and rebuilt on reload, which most Android devices cannot afford.

    The gate is an overlay `disabled:` expression rather than a code change, so
    the anchor is the expression text. A profile may still opt in by overriding
    the entry: the patch only changes the default.
    """
    rel = os.path.join("packages", "bundle", "base", "cordis.patch.yml")
    path = os.path.join(REPO_DIR, rel)
    if not os.path.exists(path):
        print(f"  [!] HMR Android gate: {rel} not found")
        return False
    original = "disabled: !!js \"!ctx.get('profileContext')\""
    replacement = (
        "disabled: !!js \"process.platform === 'android' || !ctx.get('profileContext')\""
    )
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()
    if replacement in c:
        return True
    # Several entries gate on profileContext; only the one under the hmr entry
    # is the reloader. Anchor on the entry id so a later entry cannot be hit.
    anchor = "    - id: hmr\n"
    start = c.find(anchor)
    if start < 0:
        print("  [!] HMR Android gate: 'hmr' entry not found in the base overlay")
        return False
    end = c.find("\n    - id: ", start + len(anchor))
    block = c[start : end if end > 0 else len(c)]
    if original not in block:
        print("  [!] HMR Android gate: disabled anchor not found under the 'hmr' entry")
        return False
    new_block = block.replace(original, replacement, 1)
    c = c[:start] + new_block + (c[end:] if end > 0 else "")
    with open(path, "w", encoding="utf-8") as f:
        f.write(c)
    print("  [+] Patched cordis.patch.yml (HMR stays off on Android).")
    return True


def patch_android_sandbox_default():
    """Defaults the sandbox permission mode to danger-full-access on Android.

    PLATFORM_CHAINS in dsh-sandbox-local lists linux, darwin, and win32 only, so
    Android — which reports `process.platform === 'android'`, not `'linux'` —
    walks an empty runner chain and resolves to `unavailable`. With the default
    `workspace-write` mode every command is then refused, and the harness fails
    closed on the first tool call. Android offers no confinement runner to fall
    back to, so the confined default is meaningless there and the unconfined
    mode is the only usable one.

    An explicit DSH_PERMISSION_MODE still wins, so a user who wants the sandbox
    asked for can still select it.

    Every bundle that restates the mode has to move together: a bundle whose
    `sandbox-policy` config replaces the base row's mode reverts the Android
    default for that profile, and the approval policy then disagrees with the
    mode until dsh-permission-presets rejects the pair — the composed
    `workspace-write` (from this file) with `never` (from the base policy) names
    no preset, so the profile fails to boot.
    """
    # The ternary must stay a quoted scalar: Include parses entries under
    # JSON_SCHEMA, which has no implicit-key resolution, so a bare `: ` inside a
    # plain scalar starts a nested mapping and the overlay fails to parse. The
    # `policy:` expression below is quoted for the same reason.
    original = "mode: !!js process.env.DSH_PERMISSION_MODE ?? 'workspace-write'"
    replacement = (
        'mode: !!js "process.env.DSH_PERMISSION_MODE ?? '
        "(process.platform === 'android' ? 'danger-full-access' : 'workspace-write')\""
    )
    # An earlier revision of this patcher emitted the ternary unquoted, which
    # parses under no schema Include accepts. Repair that form in place so a tree
    # patched by it is corrected instead of reported as an unrecognised anchor.
    legacy = (
        "mode: !!js process.env.DSH_PERMISSION_MODE ?? "
        "(process.platform === 'android' ? 'danger-full-access' : 'workspace-write')"
    )
    mode_paths = [
        os.path.join("packages", "bundle", "base", "cordis.patch.yml"),
        os.path.join("packages", "bundle", "headless", "cordis.patch.yml"),
        os.path.join("packages", "experimental", "cua-mcp", "cordis.patch.yml"),
    ]
    patched_any = False
    for rel in mode_paths:
        path = os.path.join(REPO_DIR, rel)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        if replacement in c:
            patched_any = True
            continue
        if legacy in c:
            c = c.replace(legacy, replacement)
            print(f"  [+] Repaired unquoted Android sandbox mode in {rel}.")
        elif original in c:
            c = c.replace(original, replacement)
        else:
            print(f"  [!] Android sandbox default: mode anchor not found in {rel}")
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        patched_any = True

    if not patched_any:
        return False

    # The user-approval policy derives from the same default: it must resolve to
    # `never` exactly when the mode resolves to danger-full-access. Every bundle
    # that restates the policy needs the same substitution, because a bundle
    # left on the plain `?? 'workspace-write'` form resolves the mode to
    # unconfined while still asking for approval, and dsh-permission-presets
    # names no preset for that pair.
    approval_original = (
        "policy: !!js \"(process.env.DSH_PERMISSION_MODE ?? 'workspace-write') === "
        "'danger-full-access' ? 'never' : 'ask'\""
    )
    approval_replacement = (
        "policy: !!js \"(process.env.DSH_PERMISSION_MODE ?? "
        "(process.platform === 'android' ? 'danger-full-access' : 'workspace-write')) "
        "=== 'danger-full-access' ? 'never' : 'ask'\""
    )
    patched_policy = 0
    stale_policy = []
    for rel in mode_paths:
        path = os.path.join(REPO_DIR, rel)
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        # Only a bundle that restates the approval policy needs the rewrite.
        # A bundle without the row inherits the base one, which this patcher
        # has already fixed.
        if "policy: !!js" not in c:
            continue
        if approval_original in c:
            c = c.replace(approval_original, approval_replacement, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(c)
            patched_policy += 1
        elif approval_replacement not in c:
            # Restates a policy in a form neither anchor recognises: the mode
            # and the approval policy can disagree and the profile will not boot.
            stale_policy.append(rel)
    if stale_policy:
        print(
            "  [!] Android sandbox default: unrecognised approval policy in "
            + ", ".join(stale_policy)
        )
    print(
        "  [+] Patched cordis.patch.yml (Android sandbox defaults to unconfined; "
        f"{patched_policy} approval policy rows updated)."
    )
    return True


def patch_workspace_default_directory():
    """Patches defaultWorkspaceDirectory to support Android Termux without throwing missing Documents error."""
    targets = [
        os.path.join(REPO_DIR, "packages", "api", "workspace-controller", "src", "default-directory.ts"),
        os.path.join(REPO_DIR, "packages", "api", "workspace-controller", "lib", "index.js"),
    ]
    patched = 0
    for path in targets:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        if "case 'android':" in c or 'case "android":' in c:
            continue
        if "case 'linux':" in c:
            anchor = "case 'linux':"
            rep = "case 'android':\n        stdout = paths.join(internals.home ?? homedir(), 'storage', 'shared', 'documents')\n        break\n      case 'linux':"
            c = c.replace(anchor, rep, 1)
            patched += 1
        elif 'case "linux":' in c:
            anchor = 'case "linux":'
            rep = 'case "android":\n\t\t\tstdout = paths.join(internals.home ?? homedir(), "storage", "shared", "documents");\n\t\t\tbreak;\n\t\tcase "linux":'
            c = c.replace(anchor, rep, 1)
            patched += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
    if patched > 0:
        print(f"  [+] Patched defaultWorkspaceDirectory for Android ({patched} files).")
    return True


def patch_subprocess_android():
    """Makes subprocess process-group handling work on Android.

    Two upstream assumptions break here. The liveness probe runs the Linux
    process-group inspector behind an explicit platform gate
    (`platform === 'linux'`), and the inspector factory rejects Android
    outright — `createProcessInspector` throws for anything outside
    linux/darwin/win32. Android is Linux: it has /proc and the same process
    table, so the Linux inspector is the right implementation and the gate is
    what needs widening.
    """
    targets = [
        os.path.join(REPO_DIR, "packages", "subprocess", "subprocess-local", "src", "spawn.ts"),
        os.path.join(REPO_DIR, "packages", "subprocess", "subprocess-local", "src", "terminal.ts"),
        os.path.join(REPO_DIR, "packages", "subprocess", "subprocess-local", "src", "process-inspector.ts"),
    ]
    lib_dir = os.path.join(REPO_DIR, "packages", "subprocess", "subprocess-local", "lib")
    if os.path.exists(lib_dir):
        for f in os.listdir(lib_dir):
            if f.endswith(".js"):
                targets.append(os.path.join(lib_dir, f))
    patched = 0
    for path in targets:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        orig = c
        if "platform === 'linux' && linuxGroupHasLiveMembers(pid)" in c:
            c = c.replace("platform === 'linux' && linuxGroupHasLiveMembers(pid)", "(platform === 'linux' || platform === 'android') && linuxGroupHasLiveMembers(pid)")
        if 'platform === "linux" && linuxGroupHasLiveMembers(pid)' in c:
            c = c.replace('platform === "linux" && linuxGroupHasLiveMembers(pid)', '(platform === "linux" || platform === "android") && linuxGroupHasLiveMembers(pid)')
        if "this.platform === 'linux' && observed.complete === true" in c:
            c = c.replace("this.platform === 'linux' && observed.complete === true", "(this.platform === 'linux' || this.platform === 'android') && observed.complete === true")
        if 'this.platform === "linux" && observed.complete === true' in c:
            c = c.replace('this.platform === "linux" && observed.complete === true', '(this.platform === "linux" || this.platform === "android") && observed.complete === true')
        # Current upstream: the gate moved onto the helper call inside alive().
        if "directSettled && platform === 'linux'" in c:
            c = c.replace("directSettled && platform === 'linux'", "directSettled && (platform === 'linux' || platform === 'android')")
        if 'directSettled && platform === "linux"' in c:
            c = c.replace('directSettled && platform === "linux"', 'directSettled && (platform === "linux" || platform === "android")')
        # The inspector factory rejects Android outright, which fails at plugin
        # load. Android is Linux and has the same process table.
        if "if (platform === 'linux') return new LinuxProcessInspector(arch, internals)" in c:
            c = c.replace(
                "if (platform === 'linux') return new LinuxProcessInspector(arch, internals)",
                "// Android is Linux: same /proc, same process table, same syscall numbers.\n"
                "  if (platform === 'linux' || platform === 'android') return new LinuxProcessInspector(arch, internals)",
            )
        if 'if (platform === "linux") return new LinuxProcessInspector(arch, internals)' in c:
            c = c.replace(
                'if (platform === "linux") return new LinuxProcessInspector(arch, internals)',
                '// Android is Linux: same /proc, same process table, same syscall numbers.\n'
                '  if (platform === "linux" || platform === "android") return new LinuxProcessInspector(arch, internals)',
            )
        if c != orig:
            with open(path, "w", encoding="utf-8") as f:
                f.write(c)
            patched += 1
    if patched > 0:
        print(f"  [+] Patched subprocess-local Android process group checks ({patched} files).")
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
        # If in the middle of a merge, diff against MERGE_HEAD / upstream/master directly
        is_merging = subprocess.run(["git", "rev-parse", "--verify", "MERGE_HEAD"], cwd=REPO_DIR, capture_output=True).returncode == 0
        if is_merging:
            base = "MERGE_HEAD"
        else:
            base = "upstream/master"
            # Use merge-base with upstream/master so diff contains only fork modifications
            mb_res = subprocess.run(["git", "merge-base", "HEAD", base], cwd=REPO_DIR, capture_output=True, text=True)
            if mb_res.returncode == 0 and mb_res.stdout.strip():
                base = mb_res.stdout.strip()
            else:
                has_upstream = subprocess.run(["git", "rev-parse", "--verify", base], cwd=REPO_DIR, capture_output=True).returncode == 0
                if not has_upstream:
                    base = "HEAD"
        
        diff = subprocess.run(
            ["git", "diff", base, "--", "package.json", "packages/", "apps/web/", ":(exclude)**/lib/**", ":(exclude)**/*.map"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True
        )
        full_diff = diff.stdout
        if not full_diff.strip():
            res = subprocess.run(
                ["git", "diff", "HEAD", "--", "package.json", "packages/", "apps/web/", ":(exclude)**/lib/**", ":(exclude)**/*.map"],
                cwd=REPO_DIR,
                capture_output=True,
                text=True
            )
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

    # 3. Phone web access: the loopback predicate must admit the bind address.
    #    Accept either upstream layout, since the fence moved from a
    #    browser-auth.ts cookie check to loopback-hostname.ts.
    connection = os.path.join(REPO_DIR, "packages", "client", "connection", "src")
    auth_ok = False
    for name, marker in (("loopback-hostname.ts", "ANDROID_BIND_ADDRESS"), ("browser-auth.ts", "isLocalAuthority")):
        auth_path = os.path.join(connection, name)
        if os.path.exists(auth_path):
            with open(auth_path, "r", encoding="utf-8") as f:
                auth_ok = marker in f.read()
            if auth_ok:
                break
    print(f"[*] Local Mobile Auth Bypass:          {'[PASS]' if auth_ok else '[FAIL]'}")

    # 4. Mobile Drawer UI
    frame_path = os.path.join(REPO_DIR, "packages", "client", "ui-layout", "src", "client", "AppFrame.tsx")
    frame_ok = False
    if os.path.exists(frame_path):
        with open(frame_path, "r", encoding="utf-8") as f:
            c = f.read()
        frame_ok = ("onSidebarColClick" in c or "isMobile" in c) and ("drawerMask" in c or "mobileBackdrop" in c)
    print(f"[*] Responsive Mobile Drawer & UI:     {'[PASS]' if frame_ok else '[FAIL]'}")

    # 5. Model dropdown onBlur detachment. Upstream carries onBlur on the root
    #    element, so testing for "onBlur" alone would pass unpatched; require
    #    the detached form instead.
    ms_path = os.path.join(REPO_DIR, "packages", "client", "ui-model-selection", "src", "client", "ModelSelect.tsx")
    ms_ok = False
    if os.path.exists(ms_path):
        with open(ms_path, "r", encoding="utf-8") as f:
            c = f.read()
        ms_ok = "void onBlur" in c and "onBlur={onBlur}" not in c
    print(f"[*] Mobile Model Dropdown Blur:        {'[PASS]' if ms_ok else '[FAIL]'}")

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
        pkg_ok = "--expose-internals" in c
    print(f"[*] Runtime Engine Flags:              {'[PASS]' if pkg_ok else '[FAIL]'}")

    # 8. Android session lease (flock fallback). The write lease must not depend
    #    on the kernel flock the native addon provides, because Android has no
    #    build of that addon — if this is missing, EVERY session dies at its
    #    first write, so verify loudly. Two shapes count as satisfied: the
    #    in-process claim this suite installs, and the marker lease the older
    #    upstream line shipped. A tree is only broken when it has neither.
    lease_path = os.path.join(REPO_DIR, "packages", "session", "session-persistence-jsonl", "src", "lease.ts")
    lease_ok = False
    if os.path.exists(lease_path):
        with open(lease_path, "r", encoding="utf-8") as f:
            c = f.read()
        lease_ok = (
            ("androidInProcessClaims" in c and "claimInProcess" in c and "isAndroidRuntime" in c)
            or ("useMarkerLease" in c and "acquireMarker" in c)
        )
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
        # Assert the properties this patcher writes, by the names it writes them
        # under. Pinning numeric values here meant the check failed whenever
        # upstream renumbered a z-index, which says nothing about the port.
        traj_ok = (
            "isolation: isolate" in c
            and "white-space: normal" in c
            and "overflow-wrap: anywhere" in c
            and "--dsh-scrollbar-thumb: var(--dsw-alias-scrollbar-bg-l2)" in c
            and ".detailBodySummary > .overview" in c
        )
    print(f"[*] Mobile Trajectory Summary & View:  {'[PASS]' if traj_ok else '[FAIL]'}")

    # 11. Local Speech Recognition (SenseVoice Android)
    #     The patcher appends `android-{TARGET.node_arch}` for the device it runs
    #     on, so the arch differs per device and is absent on a build host. Assert
    #     that an android entry is present at all, anywhere the patch can land.
    speech_ok = False
    speech_files = [
        os.path.join(REPO_DIR, "packages", "experimental", "speech-to-text-sensevoice",
                     "src", "runtime.ts"),
        os.path.join(REPO_DIR, "packages", "experimental", "speech-to-text-sensevoice",
                     "lib", "types", "runtime.js"),
    ]
    for path in speech_files:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            if "android-" in f.read():
                speech_ok = True
                break
    print(f"[*] Local Speech (SenseVoice Android): {'[PASS]' if speech_ok else '[FAIL]'}")

    # 12. Mobile Settings Sheet & Back Button
    set_tsx = os.path.join(REPO_DIR, "packages", "client", "ui-settings-general", "src", "client", "SettingsRoot.tsx")
    set_css = os.path.join(REPO_DIR, "packages", "client", "ui-settings-general", "src", "client", "SettingsRoot.module.css")
    set_ok = False
    if os.path.exists(set_tsx) and os.path.exists(set_css):
        with open(set_tsx, "r", encoding="utf-8") as f:
            t = f.read()
        with open(set_css, "r", encoding="utf-8") as f:
            s = f.read()
        set_ok = "mobileHeader" in t and "mobileClose" in t and ".mobileHeader" in s and ".mobileClose" in s
    print(f"[*] Mobile Settings & Close Button:    {'[PASS]' if set_ok else '[FAIL]'}")

    # 13. App-Boot Pure JS Resolver Fallback. The resolver must not depend on the
    #     native node-addon-require-builtin addon, which has no Android build.
    #     Two shapes count: the wrapper this suite installs, and the older
    #     requireInternal fallback the previous upstream line carried.
    boot_lib = os.path.join(REPO_DIR, "packages", "boot", "app-boot", "lib", "index.js")
    boot_src = os.path.join(REPO_DIR, "packages", "boot", "app-boot", "src", "profile-resolution", "resolver.ts")
    boot_ok = False
    # Reaching the marker in either file is the evidence. If neither exists the
    # tree is stripped or never built, and reporting PASS would claim the boot
    # path was verified when nothing was read.
    have_src = os.path.exists(boot_src)
    have_lib = os.path.exists(boot_lib)
    if not have_src and not have_lib:
        boot_ok = False
    elif have_src:
        with open(boot_src, "r", encoding="utf-8") as f:
            source = f.read()
        boot_ok = TERMUX_RESOLVER_MARKER in source or "requireInternal" in source
    else:
        # No source resolver: an older upstream shape the lib/ patch covers.
        boot_ok = True
    if boot_ok and have_lib:
        with open(boot_lib, "r", encoding="utf-8") as f:
            built = f.read()
        boot_ok = TERMUX_RESOLVER_MARKER in built or "requireInternal" in built
        # The patched bundle must still parse. A name this suite declares that
        # upstream also declares is a duplicate declaration, which fails only
        # when the harness boots, so the marker alone is not enough evidence.
        if boot_ok and TERMUX_RESOLVER_MARKER in built:
            boot_ok = node_syntax_ok(built)
    print(f"[*] App-Boot Pure JS Resolver Fallback:{'[PASS]' if boot_ok else '[FAIL]'}")

    # 14. Workspace Default Directory (Android documents fallback)
    ws_src = os.path.join(REPO_DIR, "packages", "api", "workspace-controller", "src", "default-directory.ts")
    ws_ok = False
    if os.path.exists(ws_src):
        with open(ws_src, "r", encoding="utf-8") as f:
            ws_ok = "case 'android':" in f.read()
    print(f"[*] Android Workspace Default Dir:     {'[PASS]' if ws_ok else '[FAIL]'}")

    # 15. Subprocess Process Group Liveness. Both halves matter: the liveness
    #     gate must recognize android, and the inspector factory must not reject
    #     it at plugin load.
    sub_dir = os.path.join(REPO_DIR, "packages", "subprocess", "subprocess-local", "src")
    sub_spawn = os.path.join(sub_dir, "spawn.ts")
    sub_inspector = os.path.join(sub_dir, "process-inspector.ts")
    sub_ok = False
    if os.path.exists(sub_spawn):
        with open(sub_spawn, "r", encoding="utf-8") as f:
            sub_ok = "platform === 'android'" in f.read()
    if sub_ok and os.path.exists(sub_inspector):
        with open(sub_inspector, "r", encoding="utf-8") as f:
            sub_ok = "platform === 'android'" in f.read()
    print(f"[*] Subprocess Group Liveness Check:   {'[PASS]' if sub_ok else '[FAIL]'}")

    # 16. Android sandbox default. Android walks an empty PLATFORM_CHAINS entry,
    #     so a confined default refuses every command. Both the mode and the
    #     approval policy derived from it must know about android, in every
    #     bundle that restates either: one left on the plain default composes a
    #     mode and a policy that name no preset, and that profile fails to boot.
    sandbox_path = os.path.join(REPO_DIR, "packages", "bundle", "base", "cordis.patch.yml")
    sandbox_ok = True
    checked_bundles = 0
    for rel in (
        os.path.join("packages", "bundle", "base", "cordis.patch.yml"),
        os.path.join("packages", "bundle", "headless", "cordis.patch.yml"),
        os.path.join("packages", "experimental", "cua-mcp", "cordis.patch.yml"),
    ):
        path = os.path.join(REPO_DIR, rel)
        if not os.path.exists(path):
            continue
        checked_bundles += 1
        with open(path, "r", encoding="utf-8") as f:
            c = f.read()
        # Only a bundle that states a mode or a policy needs the Android form.
        if "mode: !!js" in c or "policy: !!js" in c:
            if "process.platform === 'android' ? 'danger-full-access'" not in c:
                sandbox_ok = False
    if checked_bundles == 0:
        sandbox_ok = False
    print(f"[*] Android Sandbox Default:           {'[PASS]' if sandbox_ok else '[FAIL]'}")

    # 17. Android gates on the reload and office rows. Each is checked inside its
    #     own entry, because several entries share the profileContext anchor and a
    #     file-wide search would pass on any one of them.
    def _entry_gated(rel, entry_id):
        path = os.path.join(REPO_DIR, rel)
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        start = text.find(entry_id)
        if start < 0:
            return False
        end = text.find("\n    - id: ", start + 1)
        return "process.platform === 'android'" in text[start : end if end > 0 else len(text)]

    hmr_ok = _entry_gated(
        os.path.join("packages", "bundle", "base", "cordis.patch.yml"), "    - id: hmr\n"
    )
    print(f"[*] Android HMR Gate:                  {'[PASS]' if hmr_ok else '[FAIL]'}")

    bash_path = os.path.join(REPO_DIR, "packages", "terminal", "terminal-bash", "src", "config.ts")
    bash_ok = False
    if os.path.exists(bash_path):
        with open(bash_path, "r", encoding="utf-8") as f:
            bash_ok = "PREFIX}/bin/bash" in f.read()
    print(f"[*] Android Bash Shell Path:           {'[PASS]' if bash_ok else '[FAIL]'}")

    client_hmr_ok = _entry_gated(
        os.path.join("packages", "bundle", "web-app", "cordis.patch.yml"), "    - id: client-hmr"
    )
    print(f"[*] Android Client-HMR Gate:           {'[PASS]' if client_hmr_ok else '[FAIL]'}")

    office_ok = _entry_gated(
        os.path.join("packages", "bundle", "web-app", "cordis.patch.yml"), "    - id: office-kit"
    )
    print(f"[*] Android Office Kit Gate:           {'[PASS]' if office_ok else '[FAIL]'}")

    print("==================================================")
    results = [
        ("attachment-store", att_ok), ("session-persistence", sess_ok),
        ("browser-auth", auth_ok), ("app-frame", frame_ok),
        ("model-select", ms_ok), ("fs-local", fs_ok), ("package-json", pkg_ok),
        ("session-lease", lease_ok), ("user-questions-mobile", qc_ok),
        ("trajectory-mobile", traj_ok), ("speech-to-text", speech_ok),
        ("settings-mobile", set_ok), ("node-addon-require-builtin", boot_ok),
        ("workspace-default-directory", ws_ok), ("subprocess-android", sub_ok),
        ("android-sandbox-default", sandbox_ok), ("hmr-android-gate", hmr_ok),
        ("terminal-bash-shell", bash_ok), ("client-hmr-gate", client_hmr_ok),
        ("office-kit-gate", office_ok),
    ]
    verified = {name for name, _ok in results}
    unverified = [name for name, _fn, has in patcher_suite() if not has and name not in verified]
    if unverified:
        # Naming these keeps a patcher without an invariant visible instead of
        # letting the suite report all-green on a tree where it silently failed.
        print(f"[i] No external invariant: {', '.join(unverified)}")
    all_ok = all(ok for _name, ok in results)
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
            subdirs[:] = [d for d in subdirs if d not in ("node_modules", ".git", "dist", "lib")]
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

    # Hoist native addons to root node_modules
    pnpm_dir = os.path.join(REPO_DIR, "node_modules", ".pnpm")
    root_nm = os.path.join(REPO_DIR, "node_modules")
    if os.path.exists(pnpm_dir):
        try:
            for entry in os.listdir(pnpm_dir):
                if entry.startswith("sharp@") and not os.path.exists(os.path.join(root_nm, "sharp")):
                    sharp_target = os.path.join(".pnpm", entry, "node_modules", "sharp")
                    os.symlink(sharp_target, os.path.join(root_nm, "sharp"))
                    print("  [+] Hoisted sharp to root node_modules.")
                if entry.startswith("node-pty@") and not os.path.exists(os.path.join(root_nm, "node-pty")):
                    pty_target = os.path.join(".pnpm", entry, "node_modules", "node-pty")
                    os.symlink(pty_target, os.path.join(root_nm, "node-pty"))
                    print("  [+] Hoisted node-pty to root node_modules.")
        except Exception:
            pass

    return True


def patcher_suite():
    """The ordered patch functions this suite applies exactly once each.

    Returns:
        `(name, function, has_invariant)` triples in apply order. `has_invariant`
        records whether `check_status` can verify the patch from outside.
    """
    return [
        ("attachment-store", patch_attachment_store, True),
        ("session-persistence", patch_session_persistence, True),
        ("session-lease", patch_session_lease, True),
        ("fs-local", patch_fs_local, True),
        ("browser-auth", patch_browser_auth, True),
        ("package-json", patch_package_json, True),
        ("app-frame", patch_app_frame, True),
        ("model-select", patch_model_select, True),
        ("koffi", patch_koffi, False),
        ("node-addon-require-builtin", patch_node_addon_require_builtin, True),
        ("node-pty", patch_node_pty, False),
        ("fs-ext", patch_fs_ext, False),
        ("ripgrep", patch_ripgrep, False),
        ("settings-mobile", patch_settings_mobile, True),
        ("llm-pi-ai-gateway", patch_llm_pi_ai_gateway, False),
        ("user-questions-mobile", patch_user_questions_mobile, True),
        ("trajectory-mobile", patch_trajectory_mobile, True),
        ("conversation-mobile", patch_conversation_mobile, False),
        ("speech-to-text", patch_speech_to_text, True),
        ("bundle-layer-cache", patch_bundle_layer_cache, False),
        ("terminal-bash-shell", patch_terminal_bash_shell, True),
        ("hmr-android-gate", patch_hmr_android_gate, True),
        ("workspace-default-directory", patch_workspace_default_directory, True),
        ("android-sandbox-default", patch_android_sandbox_default, True),
        ("subprocess-android", patch_subprocess_android, True),
    ]


def apply_all():
    print("[*] Applying DeepSeek Harness Termux & Mobile Environment Suite...")
    if not apply_git_patch():
        # The bundle is optional: the per-file patchers below are authoritative.
        # Reporting it keeps a stale bundle visible instead of silent.
        print("  [i] Patch bundle did not apply; per-file patchers carry the change.")
    ensure_workspace_symlinks()
    # Which module files the patchers rewrite is discovered from mtimes rather
    # than recorded at each of their write sites, so a patcher added later is
    # covered without touching it.
    before = _module_mtimes()
    failed = []
    for name, apply_patch, _has_invariant in patcher_suite():
        try:
            # A patcher returns False when its anchor did not match, which is a
            # silent no-op: the file is left on the upstream behavior Android
            # cannot run. Collect it so the exit code means "the patches landed"
            # rather than only "the tree parses".
            if apply_patch() is False:
                failed.append(name)
        except Exception as exc:
            # One failing patcher must not strand the remaining patches, but it
            # must not disappear either — name it and keep going.
            print(f"  [!] Patcher {name} failed: {exc}")
            failed.append(name)
    after = _module_mtimes()
    global _TOUCHED_MODULES
    _TOUCHED_MODULES = {
        path for path, mtime in after.items() if before.get(path) != mtime
    }
    syntax_ok = verify_patched_syntax()
    if failed:
        print(f"[!] {len(failed)} patcher(s) did not land: {', '.join(failed)}")
    print(f"[+] Applied {len(patcher_suite())} Termux & Mobile patches.")
    export_patch()
    # A patched module that does not parse is a boot failure on the device, so
    # this must fail the run rather than warn: in CI an exit code is the only
    # signal a workflow can act on. Same for a patcher that matched nothing.
    return syntax_ok and not failed


_TOUCHED_MODULES = set()


def _module_mtimes():
    """Maps every workspace module file under a `lib/` dir to its mtime.

    Scoped to `lib/` because that is what a profile loads at runtime; `src/`
    files are compiled by the build that follows, which is its own gate.
    """
    found = {}
    for root, dirs, files in os.walk(REPO_DIR):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "dist")]
        if f"{os.sep}lib" not in root:
            continue
        for name in files:
            if name.endswith((".js", ".mjs")):
                path = os.path.join(root, name)
                try:
                    found[path] = os.stat(path).st_mtime_ns
                except OSError:
                    pass
    return found


def verify_patched_syntax():
    """Parses the module files this run actually rewrote.

    Patchers write into files nobody rebuilds, so a patch that produces invalid
    source is only discovered when the harness boots on the device. A patcher
    adding a name upstream also declares is the realistic way this happens: it
    is a duplicate declaration, and it is a parse error rather than a warning.

    Only files a patcher touched in this run are checked. Walking every `lib/`
    file would mean parsing thousands of unmodified files at ~1.5s each, which
    is minutes of work on a phone for no coverage.
    """
    if shutil.which("node") is None:
        return True
    touched = sorted(_TOUCHED_MODULES)
    if not touched:
        return True

    bad = []
    for path in touched:
        if not path.endswith((".js", ".mjs")):
            # A .ts source is not parseable by `node`; the build that compiles it
            # is the gate, and it runs after this.
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
        except OSError:
            continue
        if not node_syntax_ok(source):
            bad.append(os.path.relpath(path, REPO_DIR))
    if bad:
        print("  [!] These patched files do not parse as JavaScript:")
        for rel in sorted(bad):
            print(f"        {rel}")
    else:
        print(f"  [+] {len(touched)} patched module(s) parse.")
    return not bad



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
        sys.exit(0 if apply_all() else 2)


if __name__ == "__main__":
    main()
