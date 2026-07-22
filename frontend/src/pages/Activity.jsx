import React from 'react'
import { Link } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'

export default function Activity() {
  const { data, error, loading } = useAsyncData(() => api.activity(), [])

  if (loading) return <div className="muted">Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  const boards = data.leaderboards

  return (
    <div>
      <h1>Activity</h1>

      <section className="card activity-col activity-recent">
        <h2>Recently published</h2>
        {data.recent_published.length === 0 && <div className="muted small">Nothing yet.</div>}
        <ul className="plain-list">
          {data.recent_published.map((pr) => (
            <li key={pr.id}>
              {pr.path ? (
                <Link to={`/prompt/${pr.path}`} className="history-message">{pr.title}</Link>
              ) : (
                <span className="history-message">{pr.title}</span>
              )}
              <span className="history-meta">
                {pr.author_name} · {formatDate(pr.merged_at)}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <div className="leaderboards-head">
        <h2>Leaderboards</h2>
        <span className="muted small">Who’s shaping the library — get on the board!</span>
      </div>

      <div className="activity-grid">
        <Leaderboard
          title="Top authors"
          subtitle="Prompts authored"
          empty="No authored prompts yet."
          entries={boards.top_authors.map((e) => ({
            key: e.name, label: e.name, count: e.count,
            unit: e.count === 1 ? 'prompt' : 'prompts',
          }))}
        />
        <Leaderboard
          title="Most favorited"
          subtitle="Stars from the team"
          empty="No favorites yet — star a prompt you love."
          entries={boards.most_favorited.map(promptEntry('favorite', 'favorites'))}
        />
        <Leaderboard
          title="Top contributors"
          subtitle="Accepted suggestions"
          empty="No accepted suggestions yet."
          entries={boards.top_contributors.map((e) => ({
            key: e.name, label: e.name, count: e.count,
            unit: 'accepted',
          }))}
        />
        <Leaderboard
          title="Most remixed"
          subtitle="Saved as a new prompt"
          empty="No remixes yet — save a copy of a prompt to start."
          entries={boards.most_remixed.map(promptEntry('remix', 'remixes'))}
        />
        <Leaderboard
          title="Most copied"
          subtitle="Copied to clipboard"
          empty="No copies logged yet."
          entries={boards.most_copied.map(promptEntry('copy', 'copies'))}
        />
      </div>
    </div>
  )
}

// Map a prompt-ranked API entry to a Leaderboard entry with a link.
function promptEntry(singular, plural) {
  return (e) => ({
    key: e.path,
    label: e.title,
    to: `/prompt/${e.path}`,
    meta: e.category,
    count: e.count,
    unit: e.count === 1 ? singular : plural,
  })
}

function Leaderboard({ title, subtitle, empty, entries }) {
  return (
    <section className="card activity-col leaderboard">
      <h2>{title}</h2>
      <div className="muted small leaderboard-sub">{subtitle}</div>
      {entries.length === 0 && <div className="muted small">{empty}</div>}
      <ol className="plain-list ranked">
        {entries.map((e, i) => (
          <li key={e.key} className={i < 3 ? `rank-${i + 1}` : ''}>
            <span className="leaderboard-row">
              {e.to ? (
                <Link to={e.to} className="history-message">{e.label}</Link>
              ) : (
                <span className="history-message">{e.label}</span>
              )}
              <span className="leaderboard-count">{e.count} {e.unit}</span>
            </span>
            {e.meta && <span className="history-meta">{e.meta}</span>}
          </li>
        ))}
      </ol>
    </section>
  )
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleDateString()
}
