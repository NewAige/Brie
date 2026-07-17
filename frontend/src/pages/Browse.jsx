import React, { useEffect, useMemo, useState } from 'react'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'
import PromptCard from '../components/PromptCard.jsx'

export default function Browse() {
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
        <input
          className="search"
          type="search"
          placeholder="Search title, tags and prompt text…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
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
      {prompts.loading && <div className="muted">Loading…</div>}
      {prompts.data && prompts.data.length === 0 && (
        <div className="empty">No prompts match. Try clearing a filter.</div>
      )}
      <div className="card-grid">
        {(prompts.data || []).map((p) => (
          <PromptCard key={p.path} prompt={p} onTagClick={setTag} />
        ))}
      </div>
    </div>
  )
}
