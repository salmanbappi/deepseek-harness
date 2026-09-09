/**
 * Cross-process write-ownership lock for one session's artifact directory,
 * held for the whole life of a write handle. The arbiter is the kernel:
 * POSIX takes a non-blocking `flock(2)` via native system support on `session.lock`
 * beside the log, and Windows holds a named kernel semaphore derived from
 * that path — never a file lock or handle, so readers, searches, and
 * directory removal proceed freely while the lock is held. Contention maps
 * to `SessionAlreadyOwnedError`; the kernel releases the lock when the
 * holder's descriptor or last object handle closes, including on any process
 * death, so a crashed holder never blocks a successor. A live but wedged
 * holder keeps the lock until its process exits: there is deliberately no
 * expiry that could expropriate a stalled writer whose resumed appends would
 * tear the log.
 * A POSIX lock names an inode, not a path, so after locking the holder
 * verifies the locked inode is still the file at the lock path and retries
 * otherwise: an unlinked-and-recreated lock file carries a fresh inode, and
 * a lock on the orphaned one proves nothing. Removing a live session's lock
 * file therefore forfeits exclusion on POSIX (nothing in the harness does
 * so); Windows has no lock file at all. Readers never touch the lock.
 * The lock is acquired at write-open of an existing artifact and, for a
 * created session, only right before its first materializing write — an
 * unmaterialized session has no filesystem footprint. Release never removes
 * the POSIX lock file: every acquired lock belongs to a materialized or
 * materializing session, and the surviving file keeps the stable inode later
 * lockers verify against. The browser worker stubs the native flock entry to
 * immediate success: it is single-process, so the in-process write claim
 * already excludes every writer.
 * @module @deepseek-ai/dsh-session-persistence-jsonl/lease
 */

import { mkdir, open, stat, readFile } from 'node:fs/promises'
import type { FileHandle } from 'node:fs/promises'
import { join } from 'node:path'
import { threadId } from 'node:worker_threads'
import { tryLockExclusive } from '@deepseek-ai/node-addon-system/flock'
import { SessionAlreadyOwnedError } from '@deepseek-ai/dsh-session-persistence'
import type { SessionId } from '@deepseek-ai/dsh-session'
import { acquireLockHandleWin32, releaseLockHandleWin32 } from './win32.ts'

/**
 * Whether this device lacks kernel flock support. Termux builds run a
 * single-process-per-user model on android-arm64, where the native addon is
 * unavailable (`ERR_FLOCK_UNSUPPORTED_PLATFORM`); there we approximate the
 * lease with a PID marker file, taking over markers left by dead processes.
 * The browser worker stubs the same entry differently — see the class doc.
 */
function useMarkerLease(): boolean {
  return process.platform === 'android'
}

/** This holder's identity: one line in the marker file (`pid:threadId`). */
const HOLDER_ID = `${process.pid}:${threadId}`

/** Parse a marker's `pid:threadId` line, or null when absent/unparsable. */
async function readMarker(path: string): Promise<{ pid: number; tid: number } | null> {
  const raw = await readFile(path, 'utf8').catch(() => null)
  if (raw === null) return null
  const match = /^([1-9]\d*):(\d+)$/.exec(raw.trim())
  return match === null ? null : { pid: Number(match[1]), tid: Number(match[2]) }
}

/** Whether a marker-holding PID is still alive (0 → kill(pid, 0) probe). */
function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch (error: unknown) {
    return (error as NodeJS.ErrnoException | null)?.code === 'EPERM'
  }
}

/**
 * In-process holder registry. Kernel flock excludes two descriptors even
 * within one process; a marker file only carries `pid:threadId`, and worker
 * threads do not share JS memory — so same-process exclusion is tracked here
 * (process-wide across threads via a shared global), keyed by lock path and
 * validated against the recorded inode so an unlinked (forfeited) lock
 * admits a successor, exactly like the kernel-locked flow.
 */
const inProcessHolders: Map<string, { holder: string; ino: string }> = (
  globalThis as unknown as { __dshLeaseHolders?: Map<string, { holder: string; ino: string }> }
).__dshLeaseHolders ??= new Map()

/**
 * Acquire the marker lease on android, where the native flock addon is
 * unavailable. Follows the POSIX open→lock→stat→retry flow so injected
 * filesystem refusals surface identically: the kernel call still runs through
 * `tryLockExclusive` (its ERR_FLOCK_UNSUPPORTED_PLATFORM rejection is the
 * android signal to fall through to marker ownership; contention and
 * non-contention errno mappings are preserved), same-process exclusion is
 * approximated by the registry, and the marker's `pid:threadId` owner must be
 * alive, with takeover of markers naming dead PIDs.
 */
async function acquireMarker(path: string, id: SessionId): Promise<HeldLock> {
  const registered = inProcessHolders.get(path)
  if (registered !== undefined) {
    const current = await stat(path, { bigint: true }).catch((error: unknown) => {
      if ((error as NodeJS.ErrnoException | null)?.code === 'ENOENT') return undefined
      throw error
    })
    if (current !== undefined && current.ino.toString() === registered.ino) {
      throw new SessionAlreadyOwnedError(id)
    }
    // The locked inode is gone or replaced: the wedged holder forfeited.
    inProcessHolders.delete(path)
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    // Same open/retry shape as the POSIX path: refusals, EACCES, EBUSY and
    // inode-swap detection behave identically to a kernel-locked device.
    const handle = await open(path, 'w')
    try {
      try {
        await tryLockExclusive(handle.fd)
      } catch (error: unknown) {
        if ((error as NodeJS.ErrnoException | null)?.code === 'ERR_FLOCK_UNSUPPORTED_PLATFORM') {
          // Android/Termux: no native addon; marker ownership below.
        } else if (isLockContention(error)) {
          throw new SessionAlreadyOwnedError(id)
        } else {
          throw error
        }
      }
      await handle.writeFile(`${HOLDER_ID}\n`)
      const held = await handle.stat({ bigint: true })
      const current = await stat(path, { bigint: true }).catch((error: unknown) => {
        if ((error as NodeJS.ErrnoException | null)?.code === 'ENOENT') return undefined
        throw error
      })
      if (current === undefined || current.ino !== held.ino || current.dev !== held.dev) {
        // The inode under our marker changed under us; retry against it.
        await handle.close()
        continue
      }
      const existing = await readMarker(path)
      const foreign = existing !== null
        && existing.pid !== process.pid
        && pidAlive(existing.pid)
      if (foreign) {
        await handle.close()
        throw new SessionAlreadyOwnedError(id)
      }
      inProcessHolders.set(path, { holder: HOLDER_ID, ino: held.ino.toString() })
      return { kind: 'marker', path, handle }
    } catch (error: unknown) {
      await handle.close()
      throw error
    }
  }
  throw new SessionAlreadyOwnedError(id)
}

/** Base name of the kernel lock file inside a session's directory. */
export const LEASE_FILENAME = 'session.lock'

/** The held kernel lock: a POSIX descriptor, a Win32 semaphore handle, or an android marker file. */
type HeldLock =
  | { readonly kind: 'posix'; readonly handle: FileHandle }
  | { readonly kind: 'win32'; readonly handle: number }
  | { readonly kind: 'marker'; readonly path: string; readonly handle: FileHandle }

/** Whether a flock failure means another descriptor holds the lock. */
function isLockContention(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException | null)?.code
  // flock(2) reports EAGAIN; some libcs spell it EWOULDBLOCK.
  return code === 'EAGAIN' || code === 'EWOULDBLOCK'
}

/**
 * One held write lock. Constructed only by {@link SessionWriteLease.acquire};
 * `release` closes the descriptor or handle, which is what releases the lock.
 */
export class SessionWriteLease {
  private released = false

  private constructor(private readonly held: HeldLock) {}

  /**
   * Acquire the session directory's kernel write lock.
   * @param dir - the session's artifact directory (created if absent).
   * @param id - the session the lock guards, for error identities.
   * @returns the held lock.
   * @throws {SessionAlreadyOwnedError} while another holder keeps the lock.
   */
  static async acquire(dir: string, id: SessionId): Promise<SessionWriteLease> {
    const path = join(dir, LEASE_FILENAME)
    // Owner-only like materializePosix's directories: the lock may create the
    // session directory first, and both creators must agree on the mode.
    await mkdir(dir, { recursive: true, mode: 0o700 })
    /* v8 ignore start -- native Windows coverage exercises this platform branch; Linux covers the POSIX peer */
    if (process.platform === 'win32') {
      let handle: number
      try {
        handle = await acquireLockHandleWin32(path)
      } catch (error: unknown) {
        // Sharing violation: another handle already holds the write exclusion.
        if ((error as NodeJS.ErrnoException | null)?.code === 'EBUSY') throw new SessionAlreadyOwnedError(id)
        throw error
      }
      return new SessionWriteLease({ kind: 'win32', handle })
    }
    /* v8 ignore stop */
    if (useMarkerLease()) return new SessionWriteLease(await acquireMarker(path, id))
    // Bounded retry: locking an inode a releasing creator just unlinked (or a
    // recreated path) re-opens the fresh file; steady state needs one pass.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const handle = await open(path, 'w')
      try {
        try {
          await tryLockExclusive(handle.fd)
        } catch (error: unknown) {
          if (isLockContention(error)) throw new SessionAlreadyOwnedError(id)
          throw error
        }
        const held = await handle.stat({ bigint: true })
        const current = await stat(path, { bigint: true }).catch((error: unknown) => {
          if ((error as NodeJS.ErrnoException | null)?.code === 'ENOENT') return undefined
          throw error
        })
        if (current !== undefined && current.ino === held.ino && current.dev === held.dev) {
          return new SessionWriteLease({ kind: 'posix', handle })
        }
      } catch (error: unknown) {
        await handle.close()
        throw error
      }
      // The locked inode is no longer the file at the lock path: start over
      // against whatever now stands there.
      await handle.close()
    }
    throw new SessionAlreadyOwnedError(id)
  }

  /**
   * Release the kernel lock by closing its descriptor or handle. The POSIX
   * lock file is never removed: every acquired lock belongs to a
   * materialized or materializing session, and keeping the file preserves
   * the stable inode later lockers verify against. Idempotent.
   */
  async release(): Promise<void> {
    if (this.released) return
    this.released = true
    /* v8 ignore start -- native Windows coverage exercises this platform branch; Linux covers the POSIX peer */
    if (this.held.kind === 'win32') {
      await releaseLockHandleWin32(this.held.handle)
      return
    }
    /* v8 ignore stop */
    if (this.held.kind === 'marker') {
      // Mirror the POSIX contract: the lock FILE stays (its stable inode is
      // what later lockers verify against) while ownership is released —
      // truncate the marker, drop the registry claim, close the descriptor.
      inProcessHolders.delete(this.held.path)
      await this.held.handle.truncate(0).catch(() => { /* best effort */ })
      await this.held.handle.close()
      return
    }
    await this.held.handle.close()
  }
}
