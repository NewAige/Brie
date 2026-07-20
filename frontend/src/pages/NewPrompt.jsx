import React, { useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'
import Icon from '../components/Icon.jsx'
import { slugify } from '../utils.js'

const NEW_CATEGORY = '__new__'

export default function NewPrompt() {
  // "Make a copy" navigates here with the source prompt in location state.
  const source = useLocation().state?.from || null

  const cats = useAsyncData(() => api.categories(), [])
  const [title, setTitle] = useState(source ? `${source.title} (Copy)` : '')
  const [category, setCategory] = useState(source ? source.category : '')
  const [newCategory, setNewCategory] = useState('')
  const [tags, setTags] = useState(source ? source.tags.join(', ') : '')
  const [intendedUse, setIntendedUse] = useState(source ? source.intended_use : '')
  const [targetModel, setTargetModel] = useState(source ? source.target_model : '')
  const [body, setBody] = useState(source ? source.body : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [sent, setSent] = useState(null)

  const effectiveCategory = category === NEW_CATEGORY ? newCategory : category
  const knownCategories = useMemo(() => new Set((cats.data || []).map((c) => c.name)), [cats.data])
  const pathPreview = useMemo(() => {
    const trimmed = effectiveCategory.trim()
    const c = knownCategories.has(trimmed) ? trimmed : slugify(effectiveCategory)
    const s = slugify(title)
    return c && s ? `${c}/${s}.md` : null
  }, [effectiveCategory, title, knownCategories])

  const ready = title.trim().length >= 3 && effectiveCategory.trim() && body.trim()

  const payload = () => ({
    title: title.trim(),
    category: effectiveCategory.trim(),
    body,
    tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
    intended_use: intendedUse.trim(),
    target_model: targetModel.trim(),
    copied_from: source ? source.path : '',
  })

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.createPrompt(payload())
      setSent({ message: res.message, draft: false })
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const saveDraft = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.createDraft(payload())
      setSent({ message: res.message, draft: true })
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <div className="detail">
        <div className="alert alert-success">{sent.message}</div>
        <p className="muted">
          {sent.draft ? (
            <>
              It&apos;s private to you until you publish it — find it under{' '}
              <Link to="/drafts">My drafts</Link>.
            </>
          ) : (
            <>
              It goes to the Community library with you as its owner — no approver
              needed. Finish publishing it under{' '}
              <Link to="/suggestions">Suggestions</Link>.
            </>
          )}
        </p>
      </div>
    )
  }

  return (
    <div className="detail">
      <div className="crumbs">
        <Link to="/">Library</Link> / <span className="muted">New prompt</span>
      </div>

      <div className="detail-head">
        <h1>{source ? 'Copy prompt' : 'New prompt'}</h1>
      </div>

      {source && (
        <div className="alert alert-info">
          Starting from <Link to={`/prompt/${source.path}`}>{source.title}</Link>.
          Your copy becomes its own prompt — the original is not changed.
        </div>
      )}

      <div className="editor card">
        <label className="field-label" htmlFor="np-title">Title</label>
        <input
          id="np-title"
          className="editor-note"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Customer Refund Email"
          maxLength={120}
        />

        <label className="field-label" htmlFor="np-category">Category</label>
        <select
          id="np-category"
          className="editor-note"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">Choose a category…</option>
          {(cats.data || []).map((c) => (
            <option key={c.name} value={c.name}>{c.name}</option>
          ))}
          <option value={NEW_CATEGORY}>New category…</option>
        </select>
        {category === NEW_CATEGORY && (
          <input
            className="editor-note"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            placeholder="New category name"
            maxLength={60}
          />
        )}

        <label className="field-label" htmlFor="np-tags">Tags (comma-separated, optional)</label>
        <input
          id="np-tags"
          className="editor-note"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="e.g. support, customer-facing"
        />

        <label className="field-label" htmlFor="np-use">When should someone use this? (optional)</label>
        <input
          id="np-use"
          className="editor-note"
          value={intendedUse}
          onChange={(e) => setIntendedUse(e.target.value)}
          placeholder="One sentence saying when to reach for this prompt"
          maxLength={300}
        />

        <label className="field-label" htmlFor="np-model">Target model (optional)</label>
        <input
          id="np-model"
          className="editor-note"
          value={targetModel}
          onChange={(e) => setTargetModel(e.target.value)}
          placeholder="e.g. internal-chatbot-v1"
          maxLength={100}
        />

        <label className="field-label" htmlFor="np-body">The prompt</label>
        <textarea
          id="np-body"
          className="editor-area"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={16}
          spellCheck="true"
          placeholder="Write the prompt itself — instructions, tone, constraints, and placeholders like [CUSTOMER NAME]."
        />

        {pathPreview && <div className="muted small">Will be saved as {pathPreview}</div>}
        {error && <div className="alert alert-error">{error}</div>}
        <div className="editor-actions">
          <button className="btn btn-primary" onClick={submit} disabled={busy || !ready}>
            <Icon name="send" size={16} /> {busy ? 'Publishing…' : 'Publish to Community'}
          </button>
          <button className="btn" onClick={saveDraft} disabled={busy || !ready}>
            <Icon name="edit" size={16} /> Save as personal draft
          </button>
          <span className="muted small">
            New prompts go to the Community library, where you stay their owner —
            no approver needed. A personal draft saves instantly and stays
            private to you until you publish it.
          </span>
        </div>
      </div>
    </div>
  )
}
