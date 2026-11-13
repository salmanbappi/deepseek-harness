/**
 * Browser-safe, zero-dependency loopback classification shared by the `/api`
 * Host fence and the package's `ctx.connection` state. The predicate stays
 * package-internal; client plugins consume the derived state through Cordis.
 */

/**
 * Whether a normalized URL hostname names the local loopback authority.
 * @param hostname - WHATWG URL hostname (IPv6 literals retain brackets).
 * @returns true for localhost, IPv6 loopback, or any IPv4 address in 127/8.
 */
const ANDROID_BIND_ADDRESS = '0.0.0.0'

export function isLoopbackHostname(hostname: string): boolean {
  // Termux serves the Web UI on 0.0.0.0, so a browser on the device reaches the
  // Host through that literal rather than through 127.0.0.1. Upstream's fence
  // treats it as an untrusted authority and answers 401 to every request, which
  // makes the mobile Web UI unusable. Named so the Android-specific widening is
  // visible at the call site rather than buried in the comparison below.
  if (hostname === ANDROID_BIND_ADDRESS) return true
  if (hostname === 'localhost' || hostname === '[::1]') return true
  const parts = hostname.split('.')
  return parts.length === 4
    && parts[0] === '127'
    && parts.every(part => /^\d{1,3}$/.test(part) && Number(part) <= 255)
}
