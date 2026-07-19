import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'

// Personal drafts (phase D): stored in the user's own Gitea fork, visible
// only to them until they publish. Everything here talks to /api/drafts —
// the server enforces the Contributor gate; this page is simply hidden from
// browsers in the nav.
export default function Drafts() {
  const [refresh, setRefresh] = useState(0)
  const { data, error, loading } = useAsyncData(() => api.drafts(), [refresh])
  const reload = () => setRefresh((n) => n + 1)

  return (
    <div>
      <div className="page-head">
        <h1>My drafts</h1>
        <Link className="btn btn-primary" to="/new">New prompt</Link>
      </div>
      <p className="muted">
        Drafts are private to you — they save instantly, without review.
        Publishing sends a draft to the library&apos;s review flow.
      </p>

      {loading && <div className="muted">Loading…</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {data && data.length === 0 && (
        <div className="empty">
          No drafts yet. Start one from <Link to="/new">New prompt</Link> with
          “Save as personal draft”.
        </div>
      )}

      <div className="history-list">
        {(data || []).map((d) => (
          <DraftItem key={d.path} draft={d} onChanged={reload} />
        ))}
      </div>
    </div>
  )
}

function DraftItem({ draft, onChanged }) {
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState(draft.body)
  const [publishing, setPublishing] = useState(false)
  const [level, setLevel] = useState('community')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  const run = async (fn, closeAfter = false) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const res = await fn()
      setNotice(res?.message || null)
      if (closeAfter) setTimeout(onChanged, 1200)
      else onChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(() => api.updateDraft(draft.path, body))
  const publish = () => {
    setPublishing(false)
    run(() => api.publishDraft(draft.path, level), true)
  }
  const remove = () => {
    if (!window.confirm('Delete this draft? This cannot be undone.')) return
    run(() => api.deleteDraft(draft.path), true)
  }

  return (
    <div className="card history-item">
      <button className="history-row" onClick={() => setOpen(!open)}>
        <span className="history-message">
          {draft.title}
          {draft.pending_pr && <span className="own-chip">in review</span>}
          {draft.on_main && <span className="own-chip">already in library</span>}
        </span>
        <span className="history-meta">{draft.path}</span>
      </button>

      {open && (
        <div className="editor">
          <label className="field-label" htmlFor={`draft-${draft.path}`}>The prompt</label>
          <textarea
            id={`draft-${draft.path}`}
            className="editor-area"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={12}
            spellCheck="true"
          />

          {publishing && (
            <div className="card">
              <div className="field-label">Publish at which level?</div>
              <label style={{ display: 'block', marginBottom: 6 }}>
                <input
                  type="radio"
                  name={`level-${draft.path}`}
                  checked={level === 'community'}
                  onChange={() => setLevel('community')}
                />{' '}
                <strong>Community</strong> — you maintain it after the first approval.
              </label>
              <label style={{ display: 'block', marginBottom: 6 }}>
                <input
                  type="radio"
                  name={`level-${draft.path}`}
                  checked={level === 'bank'}
                  onChange={() => setLevel('bank')}
                />{' '}
                <strong>Bank</strong> — every future change needs a Bank Approver.
              </label>
              <div className="editor-actions">
                <button className="btn btn-primary" onClick={publish} disabled={busy}>
                  Send for review
                </button>
                <button className="btn btn-quiet" onClick={() => setPublishing(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {error && <div className="alert alert-error">{error}</div>}
          {notice && <div className="alert alert-success">{notice}</div>}

          {!publishing && (
            <div className="editor-actions">
              <button
                className="btn btn-primary"
                onClick={save}
                disabled={busy || !body.trim() || body === draft.body}
              >
                {busy ? 'Saving…' : 'Save draft'}
              </button>
              <button
                className="btn"
                onClick={() => setPublishing(true)}
                disabled={busy || draft.pending_pr}
                title={draft.pending_pr ? 'Already waiting for review' : ''}
              >
                Publish…
              </button>
              <button className="btn btn-quiet" onClick={remove} disabled={busy}>
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
