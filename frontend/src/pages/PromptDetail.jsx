import React, { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAsyncData, useUser } from '../hooks.js'
import { api } from '../api.js'
import CopyButton from '../components/CopyButton.jsx'
import LevelBadge from '../components/LevelBadge.jsx'
import Icon from '../components/Icon.jsx'
import FavoriteButton from '../components/FavoriteButton.jsx'
import AiAssist from '../components/AiAssist.jsx'
import { buildSuggestionInstructions, SUGGESTION_TYPE } from '../aiImport.js'

export default function PromptDetail() {
  // Path after /prompt/ — may contain slashes.
  const path = decodeURIComponent(useLocation().pathname.replace(/^\/prompt\//, ''))
  const { data: prompt, error, loading, setData } = useAsyncData(() => api.prompt(path), [path])
  const user = useUser()
  const [editing, setEditing] = useState(false)
  const [sent, setSent] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [raising, setRaising] = useState(false)
  const navigate = useNavigate()

  // Cosmetic gate only — the server re-checks the role and the current level.
  const canRaise = prompt && prompt.level === 'community' &&
    (user.role === 'approver' || user.role === 'admin')

  const raiseToBank = async () => {
    const who = prompt.owner
      ? `${prompt.owner} currently maintains this prompt and will no longer ` +
        'be able to publish edits on their own.'
      : ''
    if (!window.confirm(
      `Raise "${prompt.title}" to Bank?\n\n` +
      "Bank prompts can only be changed with a Bank Approver's sign-off. " + who
    )) return
    setRaising(true)
    setSent(null)
    setActionError(null)
    try {
      const res = await api.raiseToBank(prompt.path)
      setData((p) => ({ ...p, level: 'bank' }))
      setSent(res.message)
    } catch (err) {
      setActionError(err.message)
    } finally {
      setRaising(false)
    }
  }

  if (loading) return <div className="spinner-row"><span className="spinner" /> Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  return (
    <div className="detail">
      <div className="crumbs">
        <Link to="/">Library</Link> / <span className="muted">{prompt.category}</span>
      </div>

      <div className="detail-head">
        <h1>{prompt.title}</h1>
        <LevelBadge level={prompt.level} owner={prompt.owner} />
        {prompt.level === 'community' && prompt.owner && prompt.owner === user.username && (
          <span className="badge badge-owner" title="You can publish changes to this prompt without waiting for an approver.">
            You maintain this
          </span>
        )}
      </div>

      <div className="meta-card card">
        <dl className="meta-grid">
          {prompt.intended_use && (
            <>
              <dt>Intended use</dt>
              <dd>{prompt.intended_use}</dd>
            </>
          )}
          {prompt.target_model && (
            <>
              <dt>Target model</dt>
              <dd>{prompt.target_model}</dd>
            </>
          )}
          {prompt.author && (
            <>
              <dt>Author</dt>
              <dd>{prompt.author}</dd>
            </>
          )}
          {prompt.copied_from && (
            <>
              <dt>Copied from</dt>
              <dd><Link to={`/prompt/${prompt.copied_from}`}>{prompt.copied_from}</Link></dd>
            </>
          )}
          {prompt.review_notes && (
            <>
              <dt>Review notes</dt>
              <dd>{prompt.review_notes}</dd>
            </>
          )}
          {prompt.tags.length > 0 && (
            <>
              <dt>Tags</dt>
              <dd className="tags">
                {prompt.tags.map((t) => (
                  <span key={t} className="tag tag-static">{t}</span>
                ))}
              </dd>
            </>
          )}
        </dl>
      </div>

      {prompt.status === 'deprecated' && (
        <div className="alert alert-warn">
          This prompt is deprecated and hidden from browsing. Check the library
          for its replacement before using it.
        </div>
      )}

      <div className="body-actions">
        <CopyButton text={prompt.body} path={prompt.path} large />
        <FavoriteButton path={prompt.path} favorited={prompt.favorited} large />
        {user.role !== 'browser' && (
          <>
            <button className="btn" onClick={() => { setEditing(!editing); setSent(null) }}>
              <Icon name="edit" size={16} /> {editing ? 'Cancel suggestion' : 'Suggest an edit'}
            </button>
            <button className="btn" onClick={() => navigate('/new', { state: { from: prompt } })}>
              <Icon name="doc" size={16} /> Make a copy
            </button>
          </>
        )}
        {canRaise && (
          <button
            className="btn"
            onClick={raiseToBank}
            disabled={raising}
            title="Bank prompts can only be changed with a Bank Approver's sign-off."
          >
            {raising ? 'Raising…' : 'Raise to Bank'}
          </button>
        )}
        <Link className="btn btn-quiet" to={`/history/${prompt.path}`}>
          <Icon name="history" size={16} /> History
        </Link>
      </div>

      {sent && <div className="alert alert-success">{sent}</div>}
      {actionError && <div className="alert alert-error">{actionError}</div>}

      {editing ? (
        <SuggestEditor
          prompt={prompt}
          onDone={(msg) => {
            setEditing(false)
            setSent(msg)
          }}
        />
      ) : (
        <pre className="prompt-body">{prompt.body}</pre>
      )}
    </div>
  )
}

function SuggestEditor({ prompt, onDone }) {
  const [body, setBody] = useState(prompt.body)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.suggest(prompt.path, body, note)
      onDone(res.message)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="editor card">
      <AiAssist
        expectedType={SUGGESTION_TYPE}
        buildInstructions={() => buildSuggestionInstructions(prompt.title, body)}
        onImport={(data) => {
          setBody(data.body)
          if (data.note) setNote(data.note)
        }}
      />
      <label className="field-label" htmlFor="suggest-body">Your improved version</label>
      <textarea
        id="suggest-body"
        className="editor-area"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={16}
        spellCheck="true"
      />
      <label className="field-label" htmlFor="suggest-note">What changed, and why?</label>
      <input
        id="suggest-note"
        className="editor-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. Softened the tone and added the required disclosure line"
        maxLength={2000}
      />
      {error && <div className="alert alert-error">{error}</div>}
      <div className="editor-actions">
        <button className="btn btn-primary" onClick={submit} disabled={busy || !note.trim() || !body.trim()}>
          {busy ? 'Sending…' : 'Send for review'}
        </button>
        <span className="muted small">
          Your suggestion goes to the prompt approvers — it changes nothing until approved.
        </span>
      </div>
    </div>
  )
}
