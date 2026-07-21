import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAsyncData, useUser } from '../hooks.js'
import { api } from '../api.js'
import PromptTable from '../components/PromptTable.jsx'
import Icon from '../components/Icon.jsx'

export default function Browse() {
  const user = useUser()
  const [category, setCategory] = useState('')
  const [tag, setTag] = useState('')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [favorites, setFavorites] = useState(false)
  const [mine, setMine] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 250)
    return () => clearTimeout(t)
  }, [query])

  const cats = useAsyncData(() => api.categories(), [])
  const prompts = useAsyncData(
    () => api.prompts({ category, tag, q: debounced, favorites, mine }),
    [category, tag, debounced, favorites, mine]
  )

  const allTags = useMemo(() => {
    const tags = new Set((prompts.data || []).flatMap((p) => p.tags))
    if (tag) tags.add(tag)
    return [...tags].sort()
  }, [prompts.data, tag])

  // Unstarring while viewing favourites would normally make the card vanish
  // mid-click, which is hostile if it was a misclick. Instead we keep the card
  // in place (its star just goes hollow) and let the next fetch drop it, so an
  // immediate re-click undoes the mistake.
  const handleFavoriteChange = (path, favorited) => {
    prompts.setData((rows) =>
      (rows || []).map((p) => (p.path === path ? { ...p, favorited } : p))
    )
  }

  // Distinguishes "you have no favourites at all" from "your favourites exist
  // but nothing here matches the other filters" — different advice each way.
  const onlyFavoritesNarrowed = Boolean(debounced || category || tag || mine)

  return (
    <div>
      <div className="page-head">
        <h1>Library</h1>
        {user.role !== 'browser' && (
          <Link className="btn btn-primary" to="/new"><Icon name="plus" size={16} /> New prompt</Link>
        )}
      </div>

      <div className="toolbar" role="group" aria-label="Search and filters">
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

        <span className="toolbar-divider" aria-hidden="true" />

        <label className="select-wrap">
          <span className="visually-hidden">Category</span>
          <select
            className="select-control"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All categories</option>
            {(cats.data || []).map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} ({c.count})
              </option>
            ))}
          </select>
          <Icon name="chevron-down" size={15} />
        </label>

        <label className="select-wrap">
          <span className="visually-hidden">Tag</span>
          <select
            className="select-control"
            value={tag}
            onChange={(e) => setTag(e.target.value)}
          >
            <option value="">All tags</option>
            {allTags.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <Icon name="chevron-down" size={15} />
        </label>

        <span className="toolbar-divider" aria-hidden="true" />

        <button
          className={`toggle ${favorites ? 'toggle-on' : ''}`}
          onClick={() => setFavorites(!favorites)}
          aria-pressed={favorites}
        >
          <Icon name="star" size={15} filled={favorites} /> Favourites
        </button>
        <button
          className={`toggle ${mine ? 'toggle-on' : ''}`}
          onClick={() => setMine(!mine)}
          aria-pressed={mine}
        >
          <Icon name="edit" size={15} /> Written by me
        </button>

        {(category || tag || favorites || mine || query) && (
          <button
            className="toggle toggle-clear"
            onClick={() => {
              setCategory('')
              setTag('')
              setFavorites(false)
              setMine(false)
              setQuery('')
            }}
          >
            <Icon name="close" size={14} /> Clear
          </button>
        )}

        {prompts.data && (
          <span className="toolbar-count">
            {prompts.data.length} {prompts.data.length === 1 ? 'prompt' : 'prompts'}
            {(debounced || category || tag || favorites || mine) ? ' found' : ''}
          </span>
        )}
      </div>

      {prompts.error && <div className="alert alert-error">{prompts.error}</div>}
      {prompts.data && prompts.data.length === 0 && (
        <div className="empty">
          <Icon name={favorites ? 'star' : 'search'} />
          {favorites && !onlyFavoritesNarrowed ? (
            <>
              <strong>No favourites yet</strong>
              <span>Star a prompt from any card or its page to find it here later.</span>
            </>
          ) : mine && !debounced && !category && !tag && !favorites ? (
            <>
              <strong>You haven't written any prompts yet</strong>
              <span>Prompts you author or maintain will appear here.</span>
            </>
          ) : (
            <>
              <strong>No prompts match</strong>
              <span>Try a different search, or clear a filter above.</span>
            </>
          )}
        </div>
      )}
      {(prompts.loading || (prompts.data || []).length > 0) && (
        <PromptTable
          prompts={prompts.data}
          loading={prompts.loading}
          onTagClick={setTag}
          activeTag={tag}
          onFavoriteChange={handleFavoriteChange}
        />
      )}
    </div>
  )
}
