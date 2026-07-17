import React, { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'
import DiffView from '../components/DiffView.jsx'

export default function History() {
  const path = decodeURIComponent(useLocation().pathname.replace(/^\/history\//, ''))
  const { data, error, loading } = useAsyncData(() => api.history(path), [path])
  const [open, setOpen] = useState(null)

  return (
    <div className="detail">
      <div className="crumbs">
        <Link to="/">Library</Link> / <Link to={`/prompt/${path}`}>{path.split('/').pop()}</Link> /{' '}
        <span className="muted">history</span>
      </div>
      <h1>History</h1>
      <p className="muted">Every published change to this prompt: who, when, and what.</p>

      {loading && <div className="muted">Loading…</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="history-list">
        {(data || []).map((commit) => (
          <div key={commit.sha} className="card history-item">
            <button
              className="history-row"
              onClick={() => setOpen(open === commit.sha ? null : commit.sha)}
            >
              <span className="history-message">{firstLine(commit.message)}</span>
              <span className="history-meta">
                {commit.author} · {formatDate(commit.date)}
              </span>
            </button>
            {open === commit.sha && (
              <div className="history-diff">
                {restLines(commit.message) && (
                  <p className="muted small history-note">{restLines(commit.message)}</p>
                )}
                <DiffView diff={commit.diff} />
              </div>
            )}
          </div>
        ))}
        {data && data.length === 0 && <div className="empty">No history found.</div>}
      </div>
    </div>
  )
}

const firstLine = (msg) => (msg || '').split('\n')[0]
const restLines = (msg) => (msg || '').split('\n').slice(1).join('\n').trim()

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleString()
}
