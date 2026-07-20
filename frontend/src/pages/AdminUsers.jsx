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
// remove users, and toggle Contributor-ness (= contributors-team membership).
// "Add" can either create a brand-new Gitea account (needs a Gitea site-admin
// signed in) or just grant an existing account access; "remove" revokes access.
// Approver/Admin promotions still happen in Gitea/AD, not here.
export default function AdminUsers() {
  const user = useUser()
  const [reloadKey, setReloadKey] = useState(0)
  const { data, error, loading } = useAsyncData(() => api.adminUsers(), [reloadKey])
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState(null) // { kind: 'ok'|'error', text }
  const [newUsername, setNewUsername] = useState('')
  const [newPermission, setNewPermission] = useState('read')
  const [createAccount, setCreateAccount] = useState(false)
  const [newFullName, setNewFullName] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')

  if (user.role !== 'admin') return <div className="empty">Admins only.</div>
  if (loading) return <div className="muted">Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  const reload = () => setReloadKey((k) => k + 1)

  const resetAddForm = () => {
    setNewUsername('')
    setNewPermission('read')
    setCreateAccount(false)
    setNewFullName('')
    setNewEmail('')
    setNewPassword('')
  }

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
    const account = createAccount
      ? { email: newEmail.trim(), password: newPassword, full_name: newFullName.trim() }
      : null
    setBusy('__add__')
    setNotice(null)
    try {
      const res = await api.addUser(username, newPermission, account)
      setNotice({ kind: 'ok', text: res.message })
      resetAddForm()
      reload()
    } catch (err) {
      // Gitea's own message passes through — e.g. its 403 when the admin isn't
      // a site admin (account creation) or repo admin (access grant), or its
      // 422 when the username/email already exists.
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

  const deleteAccount = async (username) => {
    if (!window.confirm(
      `Permanently DELETE the Gitea account "${username}"?\n\n` +
      `This cannot be undone. It also purges everything the account owns in ` +
      `Gitea — their personal drafts, forks, and comments. To only take away ` +
      `library access, use "Remove" instead.`)) return
    setBusy(username)
    setNotice(null)
    try {
      const res = await api.deleteAccount(username)
      setNotice({ kind: 'ok', text: res.message })
      reload()
    } catch (err) {
      // e.g. Gitea's 403 when the admin isn't a site administrator — verbatim.
      setNotice({ kind: 'error', text: err.message })
    } finally {
      setBusy('')
    }
  }

  return (
    <div>
      <h1>Users</h1>
      <p className="muted">
        Roles come live from Gitea. Here you can add a user — either create a
        brand-new Gitea account or grant an existing one access to the library —
        remove a user (revoke that access), and change one role directly:
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
            disabled={
              busy === '__add__' ||
              !newUsername.trim() ||
              (createAccount && (!newEmail.trim() || !newPassword))
            }
          >
            {busy === '__add__' ? 'Adding…' : createAccount ? 'Create & add' : 'Add'}
          </button>
        </div>

        <label className="admin-add-toggle">
          <input
            type="checkbox"
            checked={createAccount}
            onChange={(e) => setCreateAccount(e.target.checked)}
          />
          <span>Create a new Gitea account</span>
        </label>

        {createAccount ? (
          <div className="admin-add-account">
            <div className="admin-add-row">
              <input
                className="editor-note"
                value={newFullName}
                onChange={(e) => setNewFullName(e.target.value)}
                placeholder="Full name (optional)"
                autoComplete="off"
              />
              <input
                className="editor-note"
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder="Email"
                autoComplete="off"
              />
              <input
                className="editor-note"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Temporary password"
                autoComplete="new-password"
              />
            </div>
            <div className="muted small">
              Creates the account in Gitea (you must be signed in as a Gitea site
              admin), then grants it access. The user sets their own password on
              first sign-in.
            </div>
          </div>
        ) : (
          <div className="muted small">
            The account must already exist in Gitea. Browsers can then be made
            Contributors below.
          </div>
        )}
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
                  title={isSelf ? "You can't remove your own access" : 'Remove access to the library (keeps the account)'}
                  onClick={() => removeUser(u.username)}
                >
                  Remove
                </button>
                <button
                  className="btn btn-quiet admin-delete"
                  disabled={busy === u.username || isSelf}
                  title={isSelf ? "You can't delete your own account" : 'Permanently delete the Gitea account'}
                  onClick={() => deleteAccount(u.username)}
                >
                  Delete account
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
