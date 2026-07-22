import React, { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { formatDate } from '../utils.js'
import { copyToClipboard } from './CopyButton.jsx'
import LevelBadge from './LevelBadge.jsx'
import FavoriteButton from './FavoriteButton.jsx'
import Icon from './Icon.jsx'

// The library as a data table: one prompt per row, sortable columns, and the
// quick actions (favorite / copy / use) pinned in the right-hand column.
// Sorting is purely presentational, so it lives here client-side and resets
// nothing when the filters above refetch.

const COLUMNS = [
  { key: 'title', label: 'Prompt', sortable: true },
  { key: 'category', label: 'Category', sortable: true },
  { key: 'tags', label: 'Tags' },
  { key: 'level', label: 'Governance', sortable: true },
  { key: 'updated', label: 'Updated', sortable: true },
  { key: 'actions', label: 'Actions', hiddenLabel: true },
]

// Tags stack and wrap in a narrow column, so rows with many tags get noisy.
// Show only the first few by default; the rest expand per-row on demand.
const TAG_LIMIT = 2

function compare(a, b, key) {
  if (key === 'updated') {
    // ISO timestamps compare lexically; missing dates sink to the bottom.
    if (!a.updated && !b.updated) return 0
    if (!a.updated) return 1
    if (!b.updated) return -1
    return a.updated < b.updated ? -1 : a.updated > b.updated ? 1 : 0
  }
  const cmp = String(a[key]).localeCompare(String(b[key]), undefined, { sensitivity: 'base' })
  // Tie-break on title so equal categories/levels keep a stable, readable order.
  return cmp || a.title.localeCompare(b.title, undefined, { sensitivity: 'base' })
}

function SkeletonRow() {
  return (
    <tr aria-hidden="true">
      <td><div className="skeleton skeleton-title" /></td>
      <td><div className="skeleton skeleton-line-short" /></td>
      <td><div className="skeleton skeleton-line-short" /></td>
      <td><div className="skeleton skeleton-line-short" /></td>
      <td><div className="skeleton skeleton-line-short" /></td>
      <td />
    </tr>
  )
}

export default function PromptTable({ prompts, loading, onTagClick, activeTag, onFavoriteChange }) {
  const [sort, setSort] = useState(null) // { key, dir: 'asc' | 'desc' } | null
  // path -> 'copied' | 'failed', for per-row copy feedback.
  const [copyState, setCopyState] = useState({})
  const copyTimers = useRef({})
  // path -> true when that row's tags are expanded past TAG_LIMIT.
  const [expandedTags, setExpandedTags] = useState({})

  const toggleTags = (path) => {
    setExpandedTags((s) => ({ ...s, [path]: !s[path] }))
  }

  const rows = useMemo(() => {
    const list = [...(prompts || [])]
    if (sort) {
      list.sort((a, b) => (sort.dir === 'asc' ? 1 : -1) * compare(a, b, sort.key))
    }
    return list
  }, [prompts, sort])

  const toggleSort = (key) => {
    setSort((s) => {
      if (s?.key !== key) {
        // Dates read best newest-first; text columns A→Z.
        return { key, dir: key === 'updated' ? 'desc' : 'asc' }
      }
      return { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
    })
  }

  const flashCopy = (path, state) => {
    setCopyState((s) => ({ ...s, [path]: state }))
    clearTimeout(copyTimers.current[path])
    copyTimers.current[path] = setTimeout(
      () => setCopyState((s) => ({ ...s, [path]: undefined })),
      2000
    )
  }

  // The list payload deliberately omits bodies, so a row copy fetches the one
  // prompt first. Same rule as everywhere: only the body is ever copied.
  const copyRow = async (path) => {
    try {
      const prompt = await api.prompt(path)
      await copyToClipboard(prompt.body)
      api.logCopy(path)
      flashCopy(path, 'copied')
    } catch {
      flashCopy(path, 'failed')
    }
  }

  return (
    <div className="table-wrap">
      <table className="prompt-table">
        <thead>
          <tr>
            {COLUMNS.map((col) => {
              const active = sort?.key === col.key
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={`pt-col-${col.key}`}
                  aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                >
                  {col.sortable ? (
                    <button
                      className={`sort-btn ${active ? 'sort-active' : ''} ${active && sort.dir === 'asc' ? 'sort-asc' : ''}`}
                      onClick={() => toggleSort(col.key)}
                    >
                      {col.label}
                      <Icon name="chevron-down" size={13} />
                    </button>
                  ) : col.hiddenLabel ? (
                    <span className="visually-hidden">{col.label}</span>
                  ) : (
                    col.label
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {loading
            ? [1, 2, 3, 4, 5, 6].map((n) => <SkeletonRow key={n} />)
            : rows.map((p) => (
                <tr key={p.path}>
                  <td className="pt-col-title">
                    <Link className="pt-title" to={`/prompt/${p.path}`}>{p.title}</Link>
                    {p.intended_use && <span className="pt-desc">{p.intended_use}</span>}
                  </td>
                  <td className="pt-col-category">
                    <span className="pt-category">{p.category}</span>
                  </td>
                  <td className="pt-col-tags">
                    <span className="tags">
                      {(expandedTags[p.path] ? p.tags : p.tags.slice(0, TAG_LIMIT)).map((tag) => (
                        <button
                          key={tag}
                          className={`tag ${tag === activeTag ? 'tag-active' : ''}`}
                          onClick={() => onTagClick?.(tag)}
                        >
                          {tag}
                        </button>
                      ))}
                      {p.tags.length > TAG_LIMIT && (
                        <button
                          type="button"
                          className="tag tag-more"
                          aria-expanded={!!expandedTags[p.path]}
                          onClick={() => toggleTags(p.path)}
                        >
                          {expandedTags[p.path] ? 'Show less' : `+${p.tags.length - TAG_LIMIT} more`}
                        </button>
                      )}
                    </span>
                  </td>
                  <td className="pt-col-level">
                    <LevelBadge level={p.level} owner={p.owner} compact />
                  </td>
                  <td className="pt-col-updated">
                    <span className="pt-date">{formatDate(p.updated) || '—'}</span>
                    {p.author && <span className="pt-author">{p.author}</span>}
                  </td>
                  <td className="pt-col-actions">
                    <FavoriteButton
                      path={p.path}
                      favorited={p.favorited}
                      onChange={onFavoriteChange}
                    />
                    <button
                      className={`icon-btn ${copyState[p.path] === 'copied' ? 'icon-btn-success' : ''}`}
                      onClick={() => copyRow(p.path)}
                      title={copyState[p.path] === 'failed'
                        ? 'Copy failed — open the prompt and copy from there'
                        : 'Copy the prompt text to your clipboard'}
                      aria-label={`Copy ${p.title}`}
                    >
                      <Icon
                        name={copyState[p.path] === 'copied' ? 'check'
                          : copyState[p.path] === 'failed' ? 'close' : 'copy'}
                        size={16}
                      />
                    </button>
                    <Link className="btn btn-sm" to={`/prompt/${p.path}`}>Details</Link>
                  </td>
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  )
}
