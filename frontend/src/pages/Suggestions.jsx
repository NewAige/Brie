import React, { useState } from 'react'
import { useAsyncData, useUser } from '../hooks.js'
import { api } from '../api.js'
import DiffView from '../components/DiffView.jsx'
import Icon from '../components/Icon.jsx'

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

  const decided = () => {
    // Let the nav badge refresh right away, then reload the list.
    window.dispatchEvent(new Event('suggestions-changed'))
    setRefresh((n) => n + 1)
  }

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
          You’re an approver — review each change below, accept all of it or just the parts
          that look right, or decline it.
        </p>
      )}

      {loading && <div className="spinner-row"><span className="spinner" /> Loading…</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {shown && shown.length === 0 && (
        <div className="empty">
          <Icon name="inbox" />
          <strong>{tab === 'open' ? 'All caught up' : 'Nothing decided yet'}</strong>
          <span>
            {tab === 'open'
              ? 'No suggestions are waiting for review.'
              : 'Approved and declined suggestions will appear here.'}
          </span>
        </div>
      )}

      <div className="history-list">
        {(shown || []).map((pr) => (
          <SuggestionItem
            key={pr.id}
            pr={pr}
            canApprove={canApprove && pr.state === 'open'}
            // Anyone may publish a change to a prompt they own, with no
            // approver — approvers included, for whom this is the only way to
            // publish their own community prompt (Gitea refuses self-approval).
            // Owner-publish wins over the approver button when both apply, so
            // the label matches the path the backend will actually take.
            canPublishAsOwner={pr.state === 'open' && !!pr.owner_mergeable}
            isPeerSuggestion={!!pr.needs_your_review}
            isOwn={pr.author === user.username}
            onDecided={decided}
          />
        ))}
      </div>
    </div>
  )
}

function stateBadge(pr) {
  if (pr.state === 'merged') return { cls: 'badge-approved', label: 'Published' }
  if (pr.outcome === 'partial') return { cls: 'badge-partial', label: 'Partly published' }
  return { cls: 'badge-deprecated', label: 'Declined' }
}

function SuggestionItem({ pr, canApprove, canPublishAsOwner, isPeerSuggestion, isOwn, onDecided }) {
  const canDecide = canApprove || canPublishAsOwner
  const [open, setOpen] = useState(false)
  // `view` is { review } for deciders (per-change checkboxes) or { diff }
  // as the read-only / fallback rendering.
  const [view, setView] = useState(null)
  const [selected, setSelected] = useState({}) // "path:hunkIndex" -> bool
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const [declining, setDeclining] = useState(false)
  const [note, setNote] = useState('')

  const toggle = async () => {
    setOpen(!open)
    if (open || view !== null) return
    if (canDecide) {
      try {
        const review = await api.pullReview(pr.id)
        const initial = {}
        review.files.forEach((f) =>
          f.hunks.forEach((h) => { initial[`${f.path}:${h.index}`] = true })
        )
        setSelected(initial)
        setView({ review })
        return
      } catch {
        // Too large/complex for per-change review — fall back to the plain
        // diff below; publish-all and decline still work.
      }
    }
    try {
      const res = await api.pullDiff(pr.id)
      setView({ diff: res.diff })
    } catch (err) {
      setView({ diff: `Could not load the change: ${err.message}` })
    }
  }

  const review = view?.review
  const total = review ? review.files.reduce((n, f) => n + f.hunks.length, 0) : 0
  const accepted = review ? Object.values(selected).filter(Boolean).length : 0
  const partial = review && accepted < total

  const finish = (message) => {
    setDone(message)
    setTimeout(onDecided, 1200)
  }

  const publish = async () => {
    setBusy(true)
    setError(null)
    try {
      if (!partial) {
        finish((await api.merge(pr.id)).message)
      } else {
        const files = review.files.map((f) => ({
          path: f.path,
          hunks: f.hunks.filter((h) => selected[`${f.path}:${h.index}`]).map((h) => h.index),
        }))
        finish((await api.pullApply(pr.id, {
          head_sha: review.head_sha,
          base_sha: review.base_sha,
          files,
        })).message)
      }
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const decline = async () => {
    setBusy(true)
    setError(null)
    try {
      finish((await api.pullDecline(pr.id, note.trim())).message)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const publishLabel = partial
    ? `Publish ${accepted} of ${total} changes`
    : canPublishAsOwner
      ? (isPeerSuggestion ? 'Approve & publish' : 'Publish')
      : 'Approve & publish'

  const badge = pr.state !== 'open' ? stateBadge(pr) : null

  return (
    <div className="card history-item">
      <button className="history-row" onClick={toggle}>
        <span className="history-message">
          {pr.title}
          {isOwn && <span className="own-chip">yours</span>}
          {isPeerSuggestion && <span className="own-chip">needs your review</span>}
          {badge && <span className={`badge ${badge.cls}`}>{badge.label}</span>}
        </span>
        <span className="history-meta">
          {pr.author_name} · {new Date(pr.created_at).toLocaleString()}
        </span>
      </button>
      {open && (
        <div className="history-diff">
          {pr.note && <p className="history-note"><strong>Note:</strong> {pr.note}</p>}
          {view === null && <div className="spinner-row small"><span className="spinner" /> Loading change…</div>}
          {view?.diff !== undefined && <DiffView diff={view.diff} />}
          {review && (
            <ReviewHunks
              review={review}
              selected={selected}
              locked={busy || !!done}
              onToggle={(key) => setSelected((s) => ({ ...s, [key]: !s[key] }))}
            />
          )}
          {error && <div className="alert alert-error">{error}</div>}
          {done && <div className="alert alert-success">{done}</div>}
          {canDecide && !done && view !== null && (
            <>
              <div className="editor-actions">
                <button
                  className="btn btn-primary"
                  onClick={publish}
                  disabled={busy || (review && accepted === 0)}
                >
                  {busy ? 'Working…' : publishLabel}
                </button>
                <button
                  className="btn btn-quiet btn-decline"
                  onClick={() => setDeclining((d) => !d)}
                  disabled={busy}
                >
                  Decline…
                </button>
                {review && accepted === 0 ? (
                  <span className="muted small">
                    No changes selected — decline the suggestion instead.
                  </span>
                ) : canPublishAsOwner ? (
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
              {declining && (
                <div className="decline-box">
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Why is this being declined? (optional — shared with the author)"
                    disabled={busy}
                  />
                  <div className="editor-actions">
                    <button className="btn btn-danger" onClick={decline} disabled={busy}>
                      {busy ? 'Working…' : 'Decline suggestion'}
                    </button>
                    {partial && accepted > 0 && (
                      <span className="muted small">
                        Declining rejects the whole suggestion — use “{publishLabel}” to keep the parts you ticked.
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
          {!canDecide && isOwn && pr.state === 'open' && !done && view !== null && (
            <div className="editor-actions">
              <button className="btn btn-quiet btn-decline" onClick={decline} disabled={busy}>
                {busy ? 'Working…' : 'Withdraw suggestion'}
              </button>
              <span className="muted small">
                This is your suggestion — withdrawing takes it out of the review queue.
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// The suggestion's edits, one card per change, each acceptable on its own.
function ReviewHunks({ review, selected, locked, onToggle }) {
  const files = review.files.filter((f) => f.hunks.length > 0)
  if (files.length === 0) return <div className="muted small">No changes.</div>
  const showPaths = review.files.length > 1
  return (
    <div>
      {files.map((f) => (
        <div key={f.path}>
          {showPaths && (
            <div className="hunk-file">
              {f.path}
              {f.status === 'added' && <span className="own-chip">new prompt</span>}
              {f.status === 'removed' && <span className="own-chip">removed</span>}
            </div>
          )}
          {f.hunks.map((h) => {
            const key = `${f.path}:${h.index}`
            const on = !!selected[key]
            return (
              <div key={key} className={`hunk ${on ? '' : 'hunk-skipped'}`}>
                <label className="hunk-head">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => onToggle(key)}
                    disabled={locked}
                  />
                  <span>{on ? 'Accept this change' : 'Change declined'}</span>
                  <span className="hunk-counts">+{h.added} −{h.removed}</span>
                </label>
                <DiffView diff={h.lines.join('\n')} />
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
