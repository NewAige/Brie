import React, { useState } from 'react'
import { api } from '../api.js'
import { useAsyncData, useUser } from '../hooks.js'

const ROLE_LABELS = {
  browser: 'Browser',
  contributor: 'Contributor',
  approver: 'Bank Approver',
  admin: 'Admin',
}

// Minimal user management (PLAN.MD phase E): list everyone with access and
// toggle Contributor-ness (= contributors-team membership). All other role
// changes (approver, admin) happen in Gitea/AD, not here.
export default function AdminUsers() {
  const user = useUser()
  const [reloadKey, setReloadKey] = useState(0)
  const { data, error, loading } = useAsyncData(() => api.adminUsers(), [reloadKey])
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState(null) // { kind: 'ok'|'error', text }

  if (user.role !== 'admin') return <div className="empty">Admins only.</div>
  if (loading) return <div className="muted">Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  const toggle = async (username, member) => {
    setBusy(username)
    setNotice(null)
    try {
      const res = await api.setContributor(username, member)
      setNotice({ kind: 'ok', text: res.message })
      setReloadKey((k) => k + 1)
    } catch (err) {
      // Gitea's own message passes through — e.g. its 403 when the signed-in
      // admin is not an org owner, which is what team changes require.
      setNotice({ kind: 'error', text: err.message })
    } finally {
      setBusy('')
    }
  }

  return (
    <div>
      <h1>Users</h1>
      <p className="muted">
        Roles come live from Gitea. This page can only change one thing:
        membership in the <code>contributors</code> team, which turns a
        read-only Browser into a Contributor. Approver and Admin are granted in
        Gitea (or AD) directly. Where the team is synced from an AD group, the
        sync overwrites changes made here.
      </p>

      {notice && (
        <div className={`alert ${notice.kind === 'ok' ? 'alert-success' : 'alert-error'}`}>
          {notice.text}
        </div>
      )}
      {!data.team_found && (
        <div className="alert alert-error">
          The <code>contributors</code> team does not exist on the org yet, so
          membership cannot be changed. Create it in Gitea first.
        </div>
      )}

      <div className="card">
        <ul className="plain-list admin-users">
          {data.users.map((u) => (
            <li key={u.username} className="admin-user-row">
              <span className="admin-user-name">
                {u.full_name || u.username}
                {u.full_name && <span className="muted small"> · {u.username}</span>}
                {u.username === user.username && <span className="muted small"> (you)</span>}
              </span>
              <span className={`role-chip role-${u.role}`}>
                {ROLE_LABELS[u.role] || u.role}
              </span>
              {u.role === 'browser' || u.role === 'contributor' ? (
                <button
                  className="btn btn-quiet"
                  disabled={busy === u.username || !data.team_found}
                  onClick={() => toggle(u.username, !u.contributor)}
                >
                  {busy === u.username
                    ? 'Saving…'
                    : u.contributor
                      ? 'Remove from contributors'
                      : 'Make contributor'}
                </button>
              ) : (
                <span className="muted small">managed in Gitea</span>
              )}
            </li>
          ))}
        </ul>
        {data.users.length === 0 && (
          <div className="muted small">No users with access found.</div>
        )}
      </div>
    </div>
  )
}
