import React from 'react'
import { Link } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'
import Icon from '../components/Icon.jsx'

export default function Activity() {
  const { data, error, loading } = useAsyncData(() => api.activity(), [])

  if (loading) return <div className="spinner-row"><span className="spinner" /> Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  return (
    <div>
      <h1>Activity</h1>
      <p className="muted page-intro">What&apos;s moving in the library right now.</p>
      <div className="activity-grid">
        <section className="card activity-col">
          <h2><Icon name="check" size={17} /> Recently published</h2>
          {data.recent_approvals.length === 0 && <div className="muted small">Nothing yet.</div>}
          <ul className="plain-list">
            {data.recent_approvals.map((pr) => (
              <li key={pr.id}>
                <span className="history-message">{pr.title}</span>
                <span className="history-meta">
                  {pr.author_name} · {formatDate(pr.merged_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card activity-col">
          <h2><Icon name="clock" size={17} /> Awaiting review</h2>
          {data.recent_suggestions.length === 0 && <div className="muted small">Nothing waiting.</div>}
          <ul className="plain-list">
            {data.recent_suggestions.map((pr) => (
              <li key={pr.id}>
                <span className="history-message">{pr.title}</span>
                <span className="history-meta">
                  {pr.author_name} · {formatDate(pr.created_at)}
                </span>
              </li>
            ))}
          </ul>
          <Link to="/suggestions" className="muted small">Review suggestions →</Link>
        </section>

        <section className="card activity-col">
          <h2><Icon name="copy" size={17} /> Most copied</h2>
          {data.most_copied.length === 0 && <div className="muted small">No copies logged yet.</div>}
          <ol className="plain-list ranked">
            {data.most_copied.map((entry) => (
              <li key={entry.path}>
                <Link to={`/prompt/${entry.path}`} className="history-message">
                  {entry.title}
                </Link>
                <span className="history-meta">
                  {entry.category} · {entry.copies} {entry.copies === 1 ? 'copy' : 'copies'}
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  )
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleDateString()
}
