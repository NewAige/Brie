import React, { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'
import CopyButton from '../components/CopyButton.jsx'
import StatusBadge from '../components/StatusBadge.jsx'

export default function PromptDetail() {
  // Path after /prompt/ — may contain slashes.
  const path = decodeURIComponent(useLocation().pathname.replace(/^\/prompt\//, ''))
  const { data: prompt, error, loading } = useAsyncData(() => api.prompt(path), [path])
  const [mode, setMode] = useState(null) // null | 'suggest' | 'saveas'
  const [sent, setSent] = useState(null)

  if (loading) return <div className="muted">Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  const toggleMode = (next) => {
    setMode(mode === next ? null : next)
    setSent(null)
  }

  return (
    <div className="detail">
      <div className="crumbs">
        <Link to="/">Library</Link> / <span className="muted">{prompt.category}</span>
      </div>

      <div className="detail-head">
        <h1>{prompt.title}</h1>
        <StatusBadge status={prompt.status} />
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
        <FavoriteButton path={prompt.path} count={prompt.favorites} favorited={prompt.favorited} />
        <button className="btn" onClick={() => toggleMode('suggest')}>
          {mode === 'suggest' ? 'Cancel suggestion' : 'Suggest an edit'}
        </button>
        <button className="btn" onClick={() => toggleMode('saveas')}>
          {mode === 'saveas' ? 'Cancel copy' : 'Save as new prompt'}
        </button>
        <Link className="btn btn-quiet" to={`/history/${prompt.path}`}>History</Link>
      </div>

      {sent && <div className="alert alert-success">{sent}</div>}

      {mode === 'suggest' && (
        <SuggestEditor
          prompt={prompt}
          onDone={(msg) => {
            setMode(null)
            setSent(msg)
          }}
        />
      )}
      {mode === 'saveas' && (
        <SaveAsEditor
          prompt={prompt}
          onDone={(msg) => {
            setMode(null)
            setSent(msg)
          }}
        />
      )}
      {mode === null && <pre className="prompt-body">{prompt.body}</pre>}
    </div>
  )
}

function FavoriteButton({ path, count, favorited }) {
  const [on, setOn] = useState(favorited)
  const [n, setN] = useState(count)
  const [busy, setBusy] = useState(false)

  const toggle = async () => {
    setBusy(true)
    try {
      const res = await api.favorite(path, !on)
      setOn(res.favorited)
      setN(res.favorites)
    } catch {
      /* leave the button as it was */
    }
    setBusy(false)
  }

  return (
    <button
      className={`btn btn-large fav-btn ${on ? 'fav-on' : ''}`}
      onClick={toggle}
      disabled={busy}
      title={on ? 'Remove from your favorites' : 'Add to your favorites'}
    >
      {on ? '★' : '☆'} {n}
    </button>
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

function SaveAsEditor({ prompt, onDone }) {
  const { data: categories } = useAsyncData(() => api.categories(), [])
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState(prompt.category)
  const [body, setBody] = useState(prompt.body)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.saveAs(prompt.path, { title, category, body, note })
      onDone(res.message)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="editor card">
      <p className="muted small" style={{ margin: 0 }}>
        Start your own prompt from this one. It will be credited as derived
        from “{prompt.title}” and sent for review as a brand-new prompt.
      </p>
      <label className="field-label" htmlFor="saveas-title">Title for the new prompt</label>
      <input
        id="saveas-title"
        className="editor-note"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="e.g. Support reply — billing disputes"
        maxLength={200}
      />
      <label className="field-label" htmlFor="saveas-category">Category</label>
      <select
        id="saveas-category"
        className="editor-note"
        value={category}
        onChange={(e) => setCategory(e.target.value)}
      >
        {(categories || [{ name: prompt.category }]).map((c) => (
          <option key={c.name} value={c.name}>{c.name}</option>
        ))}
      </select>
      <label className="field-label" htmlFor="saveas-body">Prompt text</label>
      <textarea
        id="saveas-body"
        className="editor-area"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={16}
        spellCheck="true"
      />
      <label className="field-label" htmlFor="saveas-note">What is this copy for?</label>
      <input
        id="saveas-note"
        className="editor-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. Same structure, adapted for enterprise customers"
        maxLength={2000}
      />
      {error && <div className="alert alert-error">{error}</div>}
      <div className="editor-actions">
        <button
          className="btn btn-primary"
          onClick={submit}
          disabled={busy || !title.trim() || !note.trim() || !body.trim()}
        >
          {busy ? 'Sending…' : 'Send for review'}
        </button>
        <span className="muted small">
          New prompts go to the approvers — nothing is published until approved.
        </span>
      </div>
    </div>
  )
}
