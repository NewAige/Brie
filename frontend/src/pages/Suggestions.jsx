import React, { useState } from 'react'
import { useAsyncData, useUser } from '../hooks.js'
import { api } from '../api.js'
import DiffView from '../components/DiffView.jsx'

export default function Suggestions() {
  const user = useUser()
  const [tab, setTab] = useState('open')
  const [onlyMine, setOnlyMine] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const { data, error, loading } = useAsyncData(() => api.pulls(tab), [tab, refresh])
  const canApprove = user.role === 'approver' || user.role === 'admin'

  // Peer suggestions to prompts this user owns — flagged by the backend,
  // which is the authority on ownership. Only they can publish these.
  const needsReview = (data || []).filter((pr) => pr.needs_your_review)
  const shown = onlyMine && tab === 'open' ? needsReview : data

  return (
    <div>
      <div className="page-head">
        <h1>Suggestions</h1>
        <div className="tabs">
          <button className={`chip ${tab === 'open' ? 'chip-active' : ''}`} onClick={() => setTab('open')}>
            Awaiting review
          </button>
          <button className={`chip ${tab === 'closed' ? 'chip-active' : ''}`} onClick={() => setTab('closed')}>
            Decided
          </button>
          {tab === 'open' && needsReview.length > 0 && (
            <button
              className={`chip ${onlyMine ? 'chip-active' : ''}`}
              onClick={() => setOnlyMine(!onlyMine)}
            >
              Needs your review ({needsReview.length})
            </button>
          )}
        </div>
      </div>

      {canApprove && tab === 'open' && (data || []).length > 0 && (
        <p className="muted">
          You’re an approver — review each change below and publish it when it looks right.
        </p>
      )}

      {loading && <div className="muted">Loading…</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {shown && shown.length === 0 && (
        <div className="empty">
          {tab === 'open' ? 'No suggestions waiting for review.' : 'No decided suggestions yet.'}
        </div>
      )}

      <div className="history-list">
        {(shown || []).map((pr) => (
          <SuggestionItem
            key={pr.id}
            pr={pr}
            canApprove={canApprove && pr.state === 'open'}
            // A member may publish a change to a prompt they own, with no
            // approver. The backend authorizes this; the flag only chooses
            // which button and helper text to show.
            canPublishAsOwner={!canApprove && pr.state === 'open' && !!pr.owner_mergeable}
            isPeerSuggestion={!!pr.needs_your_review}
            isOwn={pr.author === user.username}
            onMerged={() => setRefresh((n) => n + 1)}
          />
        ))}
      </div>
    </div>
  )
}

function SuggestionItem({ pr, canApprove, canPublishAsOwner, isPeerSuggestion, isOwn, onMerged }) {
  const [open, setOpen] = useState(false)
  const [diff, setDiff] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  const toggle = async () => {
    setOpen(!open)
    if (!open && diff === null) {
      try {
        const res = await api.pullDiff(pr.id)
        setDiff(res.diff)
      } catch (err) {
        setDiff(`Could not load the change: ${err.message}`)
      }
    }
  }

  const approve = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.merge(pr.id)
      setDone(res.message)
      setTimeout(onMerged, 1200)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="card history-item">
      <button className="history-row" onClick={toggle}>
        <span className="history-message">
          {pr.title}
          {isOwn && <span className="own-chip">yours</span>}
          {isPeerSuggestion && <span className="own-chip">needs your review</span>}
          {pr.state !== 'open' && (
            <span className={`badge ${pr.state === 'merged' ? 'badge-approved' : 'badge-deprecated'}`}>
              {pr.state === 'merged' ? 'Published' : 'Declined'}
            </span>
          )}
        </span>
        <span className="history-meta">
          {pr.author_name} · {new Date(pr.created_at).toLocaleString()}
        </span>
      </button>
      {open && (
        <div className="history-diff">
          {pr.note && <p className="history-note"><strong>Note:</strong> {pr.note}</p>}
          {diff === null ? <div className="muted small">Loading change…</div> : <DiffView diff={diff} />}
          {error && <div className="alert alert-error">{error}</div>}
          {done && <div className="alert alert-success">{done}</div>}
          {(canApprove || canPublishAsOwner) && !done && (
            <div className="editor-actions">
              <button className="btn btn-primary" onClick={approve} disabled={busy}>
                {busy
                  ? 'Publishing…'
                  : canPublishAsOwner
                    ? (isPeerSuggestion ? 'Approve & publish' : 'Publish')
                    : 'Approve & publish'}
              </button>
              {canPublishAsOwner ? (
                <span className="muted small">
                  {isPeerSuggestion
                    ? `${pr.author_name} suggested this change to a prompt you maintain — approving publishes it immediately.`
                    : 'You own this prompt — publishing applies your change immediately.'}
                </span>
              ) : (
                isOwn && (
                  <span className="muted small">
                    This is your own suggestion — another approver may need to review it.
                  </span>
                )
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
