// Mirrors the server's slugify (backend/app/paths.py) closely enough for a
// live path preview. The server's derivation is always authoritative — never
// use this to decide a real path, only to show the user what one will become.
// Short display date ("12 Mar 2026") for the library table. Returns '' for a
// missing or unparseable value so callers can show their own placeholder.
export function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function slugify(text) {
  return (text || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
