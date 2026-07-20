// Mirrors the server's slugify (backend/app/paths.py) closely enough for a
// live path preview. The server's derivation is always authoritative — never
// use this to decide a real path, only to show the user what one will become.
export function slugify(text) {
  return (text || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
