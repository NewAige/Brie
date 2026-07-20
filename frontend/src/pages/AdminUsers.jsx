import React, { useState } from 'react'
import { api } from '../api.js'
import { useAsyncData, useUser } from '../hooks.js'

const ROLE_LABELS = {
  browser: 'Browser',
  contributor: 'Contributor',
  approver: 'Bank Approver',
  admin: 'Admin',
}

// Minimal user management (PLAN.MD phase E): list everyone with access, add or
// remove who has access at all, and toggle Contributor-ness (= contributors-team
// membership). Adding grants an existing Gitea account repo access; removing
// revokes it (it does not delete the account). Approver/Admin promotions still
// happen in Gitea/AD, not here.
export default function AdminUsers() {
  const user = useUser()
  const [reloadKey, setReloadKey] = useState(0)
  const { data, error, loading } = useAsyncData(() => api.adminUsers(), [reloadKey])
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState(null) // { kind: 'ok'|'error', text }
  const [newUsername, setNewUsername] = useState('')
  const [newPermission, setNewPermission] = useState('read')

  if (user.role !== 'admin') return <div className="empty">Admins only.</div>
  if (loading) return <div className="muted">Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  const reload = () => setReloadKey((k) => k + 1)

  const toggle = async (username, member) => {
    setBusy(username)
    setNotice(null)
    try {
      const res = await api.setContributor(username, member)
      setNotice({ kind: 'ok', text: res.message })
      reload()
    } catch (err) {
      // Gitea's own message passes through — e.g. its 403 when the signed-in
      // admin is not an org owner, which is what team changes require.
      setNotice({ kind: 'error', text: err.message })
    } finally {
      setBusy('')
    }
  }

  const addUser = async (e) => {
    e.preventDefault()
    const username = newUsername.trim()
    if (!username) return
    setBusy('__add__')
    setNotice(null)
    try {
      const res = await api.addUser(username, newPermission)
      setNotice({ kind: 'ok', text: res.message })
      setNewUsername('')
      setNewPermission('read')
      reload()
    } catch (err) {
      // e.g. Gitea's 404 when the username doesn't exist, or its 403 when the
      // admin lacks repo-admin rights — shown verbatim.
      setNotice({ kind: 'error', text: err.message })
    } finally {
      setBusy('')
    }
  }

  const removeUser = async (username) => {
    if (!window.confirm(
      `Remove ${username}'s access to the library? This revokes their access ` +
      `but does not delete their Gitea account.`)) return
    setBusy(username)
    setNotice(null)
    try {
      const res = await api.removeUser(username)
      setNotice({ kind: 'ok', text: res.message })
      reload()
    } catch (err) {
      setNotice({ kind: 'error', text: err.message })
    } finally {
      setBusy('')
    }
  }

  return (
    <div>
      <h1>Users</h1>
      <p className="muted">
        Roles come live from Gitea. Here you can add a user (grant an existing
        Gitea account access to the library), remove a user (revoke that access —
        the account itself stays in Gitea), and change one role directly:
        membership in the <code>contributors</code> team, which turns a read-only
        Browser into a Contributor. Approver and Admin are granted in Gitea (or
        AD) directly. Where the team is synced from an AD group, the sync
        overwrites changes made here.
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

      <form className="card admin-add" onSubmit={addUser}>
        <label className="field-label" htmlFor="admin-add-username">Add a user</label>
        <div className="admin-add-row">
          <input
            id="admin-add-username"
            className="editor-note"
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            placeholder="Gitea username"
            autoComplete="off"
          />
          <select
            className="editor-note"
            value={newPermission}
            onChange={(e) => setNewPermission(e.target.value)}
            aria-label="Access level"
          >
            <option value="read">Browser (read)</option>
            <option value="write">Bank Approver (write)</option>
          </select>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy === '__add__' || !newUsername.trim()}
          >
            {busy === '__add__' ? 'Adding…' : 'Add'}
          </button>
        </div>
        <div className="muted small">
          The account must already exist in Gitea. Browsers can then be made
          Contributors below.
        </div>
      </form>

      <div className="card">
        <ul className="plain-list admin-users">
          {data.users.map((u) => {
            const isSelf = u.username === user.username
            return (
              <li key={u.username} className="admin-user-row">
                <span className="admin-user-name">
                  {u.full_name || u.username}
                  {u.full_name && <span className="muted small"> · {u.username}</span>}
                  {isSelf && <span className="muted small"> (you)</span>}
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
                <button
                  className="btn btn-quiet admin-remove"
                  disabled={busy === u.username || isSelf}
                  title={isSelf ? "You can't remove your own access" : 'Remove access to the library'}
                  onClick={() => removeUser(u.username)}
                >
                  Remove
                </button>
              </li>
            )
          })}
        </ul>
        {data.users.length === 0 && (
          <div className="muted small">No users with access found.</div>
        )}
      </div>
    </div>
  )
}
