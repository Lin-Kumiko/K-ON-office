// Helpers for serving the app under a sub-path (for example https://host/k-on/).
// The base is fixed at build time (Vite `base`, set from DOE_BASE_PATH) and read back through import.meta.env.BASE_URL.

/** Normalise a base path to the form Vite and vue-router expect: "/" or "/segment/" with both slashes. */
export function normalizeBase(raw?: string | null): string {
  const s = (raw ?? '').trim().replace(/^\/+|\/+$/g, '')
  return s ? `/${s}/` : '/'
}

/**
 * Prefix a root-relative URL ("/api/x") with the app base.
 * Absolute URLs, protocol-relative URLs ("//host/x") and relative paths are returned unchanged.
 */
export function withBase(url: string, base?: string): string {
  if (!url.startsWith('/') || url.startsWith('//')) return url
  const b = normalizeBase(base ?? import.meta.env.BASE_URL)
  return b === '/' ? url : b.slice(0, -1) + url
}
