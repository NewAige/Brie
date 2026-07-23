// Single fetch wrapper for the backend API.
//
// Auth is an httpOnly session cookie — client JS never sees or stores any
// token (spec §5 hard requirement). A 401 anywhere flips the app to the
// sign-in screen.

export class Unauthorized extends Error {}

async function request(path, options = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: options.body ? { 'Content-Type': 'application/json' } : {},
    ...options,
  })
  if (res.status === 401) throw new Unauthorized()
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  me: () => request('/api/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),
  categories: () => request('/api/categories'),
  prompts: (params = {}) => {
    // Drop empty/absent values, and `false` flags — an omitted boolean already
    // means false to the backend, so this keeps the URL to the active filters.
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== '' && v != null && v !== false)
    ).toString()
    return request(`/api/prompts${qs ? `?${qs}` : ''}`)
  },
  prompt: (path) => request(`/api/prompts/${encodePath(path)}`),
  history: (path) => request(`/api/prompts/${encodePath(path)}/history`),
  createPrompt: (payload) =>
    request('/api/prompts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  suggest: (path, body, note) =>
    request(`/api/prompts/${encodePath(path)}/suggest`, {
      method: 'POST',
      body: JSON.stringify({ body, note }),
    }),
  // Raise a live Community prompt to Bank. Approver-only — the server
  // re-checks the role and re-reads the current level; the button that calls
  // this is only a hint. Promotion is the sole direction: there is no demote.
  raiseToBank: (path) =>
    request(`/api/prompts/${encodePath(path)}/level`, {
      method: 'POST',
      body: JSON.stringify({ level: 'bank' }),
    }),
  // Archive a prompt — retire it from browse while keeping it reachable by
  // direct link. Bank Approver / admin only; the server re-checks the role.
  // `confirm: true` is the deliberate stop-gap: the server refuses without it,
  // so the "are you sure?" dialog is a real gate, not just a UI nicety.
  archivePrompt: (path) =>
    request(`/api/prompts/${encodePath(path)}/archive`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true }),
    }),
  // Mark / unmark a prompt for the signed-in user. Returns { favorited }.
  setFavorite: (path, favorited) =>
    request(`/api/prompts/${encodePath(path)}/favorite`, {
      method: favorited ? 'PUT' : 'DELETE',
    }),
  logCopy: (path) => {
    // Fire-and-forget — a failed log must never break the copy itself.
    request('/api/events/copy', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }).catch(() => {})
  },
  drafts: () => request('/api/drafts'),
  createDraft: (payload) =>
    request('/api/drafts', { method: 'POST', body: JSON.stringify(payload) }),
  // `meta` (optional): { title, category, tags, target_model, intended_use }.
  // Omit it for a body-only save, which preserves the front-matter verbatim.
  // Returns { message, path } — the path changes when title/category do.
  updateDraft: (path, body, meta = null) =>
    request(`/api/drafts/${encodePath(path)}`, {
      method: 'PUT',
      body: JSON.stringify({ body, ...(meta || {}) }),
    }),
  deleteDraft: (path) =>
    request(`/api/drafts/${encodePath(path)}`, { method: 'DELETE' }),
  draftHistory: (path) => request(`/api/drafts/${encodePath(path)}/history`),
  publishDraft: (path, level) =>
    request(`/api/drafts/${encodePath(path)}/publish`, {
      method: 'POST',
      body: JSON.stringify({ level }),
    }),
  pulls: (state = 'open') => request(`/api/pulls?state=${state}`),
  pullDiff: (id) => request(`/api/pulls/${id}/diff`),
  // How many open suggestions the signed-in user can decide (the nav badge).
  pullsAttention: () => request('/api/pulls/attention'),
  // The suggestion split into individually acceptable changes, pinned to
  // exact revisions so a later pullApply can detect that anything moved.
  pullReview: (id) => request(`/api/pulls/${id}/review`),
  // Whole-text comparison of an open suggestion: each touched prompt's
  // current and suggested body, front-matter already stripped server-side —
  // copying a side copies exactly what the copy button would give after
  // publishing.
  pullCompare: (id) => request(`/api/pulls/${id}/compare`),
  // Publishes as approver or as prompt owner — the backend decides which,
  // and re-checks ownership itself. `pr.owner_mergeable` only picks the label.
  merge: (id) => request(`/api/pulls/${id}/merge`, { method: 'POST' }),
  // Publish only some of a suggestion's changes and decline the rest.
  // `selection` is { head_sha, base_sha, files: [{ path, hunks: [int] }] }
  // straight from pullReview plus the reviewer's choices.
  pullApply: (id, selection) =>
    request(`/api/pulls/${id}/apply`, {
      method: 'POST',
      body: JSON.stringify(selection),
    }),
  pullDecline: (id, note = '') =>
    request(`/api/pulls/${id}/decline`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  activity: () => request('/api/activity'),
  adminUsers: () => request('/api/admin/users'),
  // One call for a full role change: repo permission *and* contributors-team
  // membership, which together are what the backend derives a role from.
  // `role` is 'browser' | 'contributor' | 'approver' (admin stays Gitea-side).
  setRole: (username, role) =>
    request(`/api/admin/users/${encodeURIComponent(username)}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    }),
  // `account` (optional): { email, password, full_name } to create a brand-new
  // Gitea account before granting access. Omit it to grant an existing account.
  addUser: (username, role, account = null) =>
    request('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({ username, role, ...(account || {}) }),
    }),
  removeUser: (username) =>
    request(`/api/admin/users/${encodeURIComponent(username)}`, {
      method: 'DELETE',
    }),
  // Permanent: deletes the Gitea account itself (purges their forks/drafts).
  deleteAccount: (username) =>
    request(`/api/admin/users/${encodeURIComponent(username)}/account`, {
      method: 'DELETE',
    }),
}

// Encode each path segment but keep the slashes.
function encodePath(path) {
  return path.split('/').map(encodeURIComponent).join('/')
}
