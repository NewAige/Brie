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
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== '' && v != null)
    ).toString()
    return request(`/api/prompts${qs ? `?${qs}` : ''}`)
  },
  prompt: (path) => request(`/api/prompts/${encodePath(path)}`),
  history: (path) => request(`/api/prompts/${encodePath(path)}/history`),
  suggest: (path, body, note) =>
    request(`/api/prompts/${encodePath(path)}/suggest`, {
      method: 'POST',
      body: JSON.stringify({ body, note }),
    }),
  saveAs: (path, { title, category, body, note }) =>
    request(`/api/prompts/${encodePath(path)}/save-as`, {
      method: 'POST',
      body: JSON.stringify({ title, category, body, note }),
    }),
  favorite: (path, on) =>
    request(`/api/prompts/${encodePath(path)}/favorite`, { method: on ? 'PUT' : 'DELETE' }),
  logCopy: (path) => {
    // Fire-and-forget — a failed log must never break the copy itself.
    request('/api/events/copy', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }).catch(() => {})
  },
  pulls: (state = 'open') => request(`/api/pulls?state=${state}`),
  pullDiff: (id) => request(`/api/pulls/${id}/diff`),
  merge: (id) => request(`/api/pulls/${id}/merge`, { method: 'POST' }),
  activity: () => request('/api/activity'),
}

// Encode each path segment but keep the slashes.
function encodePath(path) {
  return path.split('/').map(encodeURIComponent).join('/')
}
