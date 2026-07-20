import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAsyncData, useUser } from '../hooks.js'
import { api } from '../api.js'
import CommitHistory from '../components/CommitHistory.jsx'
import CopyButton from '../components/CopyButton.jsx'
import Icon from '../components/Icon.jsx'
import { slugify } from '../utils.js'

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
        <Link className="btn btn-primary" to="/new"><Icon name="plus" size={16} /> New prompt</Link>
      </div>
      <p className="muted page-intro">
        Drafts are private to you — they save instantly, without review.
        Publishing puts a draft in the Community library with you as its owner.
      </p>

      {loading && <div className="spinner-row"><span className="spinner" /> Loading…</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {data && data.length === 0 && (
        <div className="empty">
          <Icon name="edit" />
          <strong>No drafts yet</strong>
          <span>
            Start one from <Link to="/new">New prompt</Link> with
            “Save as personal draft”.
          </span>
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

// The editable metadata fields, pulled off a draft. Tags are handled
// separately — they round-trip through a comma-separated text input.
const metaOf = (draft) => ({
  title: draft.title,
  category: draft.category,
  target_model: draft.target_model || '',
  intended_use: draft.intended_use || '',
})

function DraftItem({ draft, onChanged }) {
  const user = useUser()
  // Only a Bank Approver may put a prompt in the Bank tier, so everyone else
  // gets a straight Community publish with no level to choose. The backend
  // enforces this too — hiding the option is only so the UI doesn't offer
  // something that would 403.
  const canPublishToBank = user.role === 'approver' || user.role === 'admin'
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(draft.body)
  const [meta, setMeta] = useState(() => metaOf(draft))
  const [tagText, setTagText] = useState(draft.tags.join(', '))
  const [publishing, setPublishing] = useState(false)
  const [level, setLevel] = useState('community')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [history, setHistory] = useState(null)  // null = hidden, [] = loaded-empty
  const [historyError, setHistoryError] = useState(null)
  const [historyBusy, setHistoryBusy] = useState(false)

  const run = async (fn, closeAfter = false) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const res = await fn()
      setNotice(res?.message || null)
      if (closeAfter) setTimeout(onChanged, 1200)
      else onChanged()
      return true
    } catch (err) {
      setError(err.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const tags = tagText.split(',').map((t) => t.trim()).filter(Boolean)
  const dirty =
    body !== draft.body ||
    meta.title !== draft.title ||
    meta.category !== draft.category ||
    meta.target_model !== draft.target_model ||
    meta.intended_use !== draft.intended_use ||
    tags.join(',') !== draft.tags.join(',')

  const cancelEdit = () => {
    setBody(draft.body)
    setMeta(metaOf(draft))
    setTagText(draft.tags.join(', '))
    setEditing(false)
  }

  const save = async () => {
    // Only drop back to the read-only view if the save actually landed —
    // otherwise the user would lose sight of unsaved text.
    if (await run(() => api.updateDraft(draft.path, body, { ...meta, tags })))
      setEditing(false)
    // A title/category change moves the file, so the reload run() triggers
    // remounts this item under its new path (the list is keyed by path).
  }
  const publish = () => {
    setPublishing(false)
    // Community unless the user is actually allowed to pick Bank.
    run(() => api.publishDraft(draft.path,
                               canPublishToBank ? level : 'community'), true)
  }
  const remove = () => {
    if (!window.confirm('Delete this draft? This cannot be undone.')) return
    run(() => api.deleteDraft(draft.path), true)
  }
  const toggleHistory = async () => {
    if (history !== null) {
      setHistory(null)  // collapse
      return
    }
    setHistoryBusy(true)
    setHistoryError(null)
    try {
      setHistory(await api.draftHistory(draft.path))
    } catch (err) {
      setHistoryError(err.message)
    } finally {
      setHistoryBusy(false)
    }
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
          {editing ? (
            <>
              <div className="draft-meta-fields">
                <div>
                  <label className="field-label" htmlFor={`title-${draft.path}`}>Title</label>
                  <input
                    id={`title-${draft.path}`}
                    className="editor-note"
                    value={meta.title}
                    onChange={(e) => setMeta({ ...meta, title: e.target.value })}
                    maxLength={200}
                  />
                </div>
                <div>
                  <label className="field-label" htmlFor={`category-${draft.path}`}>Category</label>
                  <input
                    id={`category-${draft.path}`}
                    className="editor-note"
                    value={meta.category}
                    onChange={(e) => setMeta({ ...meta, category: e.target.value })}
                    maxLength={100}
                  />
                </div>
              </div>
              <label className="field-label" htmlFor={`tags-${draft.path}`}>Tags</label>
              <input
                id={`tags-${draft.path}`}
                className="editor-note"
                value={tagText}
                onChange={(e) => setTagText(e.target.value)}
                placeholder="comma, separated, tags"
              />
              <label className="field-label" htmlFor={`model-${draft.path}`}>Target model</label>
              <input
                id={`model-${draft.path}`}
                className="editor-note"
                value={meta.target_model}
                onChange={(e) => setMeta({ ...meta, target_model: e.target.value })}
                maxLength={200}
              />
              <label className="field-label" htmlFor={`use-${draft.path}`}>Intended use</label>
              <input
                id={`use-${draft.path}`}
                className="editor-note"
                value={meta.intended_use}
                onChange={(e) => setMeta({ ...meta, intended_use: e.target.value })}
                maxLength={2000}
              />
              {(slugify(meta.title) !== slugify(draft.title) ||
                slugify(meta.category) !== slugify(draft.category)) && (
                <div className="alert alert-warn">
                  Saving moves this draft to{' '}
                  <code>{`${slugify(meta.category)}/${slugify(meta.title)}.md`}</code>.
                </div>
              )}

              <label className="field-label" htmlFor={`draft-${draft.path}`}>The prompt</label>
              <textarea
                id={`draft-${draft.path}`}
                className="editor-area"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={12}
                spellCheck="true"
              />
            </>
          ) : (
            <>
              <div className="meta-card card">
                <dl className="meta-grid">
                  <dt>Category</dt>
                  <dd>{draft.category}</dd>
                  {draft.target_model && (
                    <>
                      <dt>Target model</dt>
                      <dd>{draft.target_model}</dd>
                    </>
                  )}
                  {draft.intended_use && (
                    <>
                      <dt>Intended use</dt>
                      <dd>{draft.intended_use}</dd>
                    </>
                  )}
                  {draft.tags.length > 0 && (
                    <>
                      <dt>Tags</dt>
                      <dd className="tags">
                        {draft.tags.map((t) => (
                          <span key={t} className="tag tag-static">{t}</span>
                        ))}
                      </dd>
                    </>
                  )}
                </dl>
              </div>
              <pre className="prompt-body">{body}</pre>
            </>
          )}

          {publishing && (
            <div className="card publish-card">
              {canPublishToBank ? (
                <>
                  <div className="field-label">Publish at which level?</div>
                  <label className="publish-option">
                    <input
                      type="radio"
                      name={`level-${draft.path}`}
                      checked={level === 'community'}
                      onChange={() => setLevel('community')}
                    />
                    <span>
                      <strong>Community</strong> — its owner maintains it, no approver needed.
                    </span>
                  </label>
                  <label className="publish-option">
                    <input
                      type="radio"
                      name={`level-${draft.path}`}
                      checked={level === 'bank'}
                      onChange={() => setLevel('bank')}
                    />
                    <span>
                      <strong>Bank</strong> — every future change needs a Bank Approver.
                    </span>
                  </label>
                </>
              ) : (
                <p className="muted small">
                  This goes to the <strong>Community</strong> library with you as its
                  owner — no approver needed. Later edits by anyone else come back
                  to you to publish. Only a Bank Approver can raise a prompt to Bank.
                </p>
              )}
              <div className="editor-actions">
                <button className="btn btn-primary" onClick={publish} disabled={busy}>
                  {canPublishToBank && level === 'bank' ? 'Send for review' : 'Publish'}
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
              <CopyButton text={body} path={draft.path} large />
              <button
                className="btn"
                onClick={() => (editing ? cancelEdit() : setEditing(true))}
                disabled={busy}
              >
                <Icon name="edit" size={16} /> {editing ? 'Cancel edit' : 'Edit draft'}
              </button>
              {editing && (
                <button
                  className="btn btn-primary"
                  onClick={save}
                  disabled={busy || !body.trim() || !meta.title.trim() ||
                            !meta.category.trim() || !dirty}
                >
                  {busy ? 'Saving…' : 'Save draft'}
                </button>
              )}
              <button
                className="btn"
                onClick={() => setPublishing(true)}
                disabled={busy || draft.pending_pr}
                title={draft.pending_pr ? 'Already waiting for review' : ''}
              >
                Publish…
              </button>
              <button className="btn" onClick={toggleHistory} disabled={historyBusy}>
                {historyBusy ? 'Loading…' : history !== null ? 'Hide history' : 'History'}
              </button>
              <button className="btn btn-quiet" onClick={remove} disabled={busy}>
                Delete
              </button>
            </div>
          )}

          {historyError && <div className="alert alert-error">{historyError}</div>}
          {history !== null && (
            <div className="history-panel">
              <p className="muted small">Every save to this draft, newest first.</p>
              <CommitHistory commits={history} emptyLabel="No saved revisions yet." />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
