import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAsyncData, useUser } from '../hooks.js'
import { api } from '../api.js'
import PromptCard from '../components/PromptCard.jsx'
import Icon from '../components/Icon.jsx'

function SkeletonCard() {
  return (
    <div className="card skeleton-card" aria-hidden="true">
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-line" />
      <div className="skeleton skeleton-line-short" />
    </div>
  )
}

export default function Browse() {
  const user = useUser()
  const [category, setCategory] = useState('')
  const [tag, setTag] = useState('')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 250)
    return () => clearTimeout(t)
  }, [query])

  const cats = useAsyncData(() => api.categories(), [])
  const prompts = useAsyncData(
    () => api.prompts({ category, tag, q: debounced }),
    [category, tag, debounced]
  )

  const allTags = useMemo(() => {
    const tags = new Set((prompts.data || []).flatMap((p) => p.tags))
    if (tag) tags.add(tag)
    return [...tags].sort()
  }, [prompts.data, tag])

  return (
    <div>
      <div className="page-head">
        <h1>Library</h1>
        <div className="search-wrap">
          <Icon name="search" size={16} />
          <input
            className="search"
            type="search"
            placeholder="Search title, tags and prompt text…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        </div>
        {user.role !== 'browser' && (
          <Link className="btn btn-primary" to="/new"><Icon name="plus" size={16} /> New prompt</Link>
        )}
      </div>

      <div className="filter-row">
        <button className={`chip ${category === '' ? 'chip-active' : ''}`} onClick={() => setCategory('')}>
          All categories
        </button>
        {(cats.data || []).map((c) => (
          <button
            key={c.name}
            className={`chip ${category === c.name ? 'chip-active' : ''}`}
            onClick={() => setCategory(category === c.name ? '' : c.name)}
          >
            {c.name} <span className="chip-count">{c.count}</span>
          </button>
        ))}
      </div>

      {allTags.length > 0 && (
        <div className="filter-row">
          {allTags.map((t) => (
            <button
              key={t}
              className={`tag ${tag === t ? 'tag-active' : ''}`}
              onClick={() => setTag(tag === t ? '' : t)}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      {prompts.error && <div className="alert alert-error">{prompts.error}</div>}
      {prompts.data && prompts.data.length === 0 && (
        <div className="empty">
          <Icon name="search" />
          <strong>No prompts match</strong>
          <span>Try a different search, or clear a filter above.</span>
        </div>
      )}
      {prompts.data && prompts.data.length > 0 && (
        <div className="muted small result-count">
          {prompts.data.length} {prompts.data.length === 1 ? 'prompt' : 'prompts'}
          {(debounced || category || tag) ? ' found' : ' in the library'}
        </div>
      )}
      <div className="card-grid">
        {prompts.loading
          ? [1, 2, 3, 4, 5, 6].map((n) => <SkeletonCard key={n} />)
          : (prompts.data || []).map((p) => (
              <PromptCard key={p.path} prompt={p} onTagClick={setTag} />
            ))}
      </div>
    </div>
  )
}
