import React, { useState } from 'react'
import DiffView from './DiffView.jsx'

// Renders a list of commits (newest first) as an accordion: click a row to
// reveal its diff. Shared by the published-prompt History page and the
// personal-drafts history panel — same shape from both backends
// ({ sha, author, date, message, diff }).
export default function CommitHistory({ commits, emptyLabel = 'No history found.' }) {
  const [open, setOpen] = useState(null)
  return (
    <div className="history-list">
      {(commits || []).map((commit) => (
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
      {commits && commits.length === 0 && <div className="empty">{emptyLabel}</div>}
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
