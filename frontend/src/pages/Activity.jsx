import React from 'react'
import { Link } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'
import Icon from '../components/Icon.jsx'

export default function Activity() {
  const { data, error, loading } = useAsyncData(() => api.activity(), [])

  if (loading) return <div className="spinner-row"><span className="spinner" /> Loading…</div>
  if (error) return <div className="alert alert-error">{error}</div>

  const boards = data.leaderboards

  return (
    <div>
      <h1>Activity</h1>
      <p className="muted page-intro">What&apos;s moving in the library right now.</p>

      <section className="card activity-col">
        <h2><Icon name="check" size={17} /> Recently published</h2>
        {data.recent_approvals.length === 0 && <div className="muted small">Nothing yet.</div>}
        <ul className="plain-list">
          {data.recent_approvals.map((pr) => (
            <li key={pr.id}>
              {/* Entries link to the prompt they published; a prompt since
                  removed from the library has nowhere to go, so no link. */}
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

      <h2 className="leaderboard-head"><Icon name="trophy" size={19} /> Leaderboards</h2>
      <p className="muted page-intro">
        Who&apos;s shaping the library — and which prompts people reach for most.
      </p>
      <div className="activity-grid">
        <Board icon="copy" title="Most copied" empty="No copies logged yet.">
          {boards.most_copied.map((entry) => (
            <PromptRow key={entry.path} entry={entry}
                       stat={count(entry.copies, 'copy', 'copies')} />
          ))}
        </Board>

        <Board icon="star" title="Most favorited" empty="No favorites yet — star a prompt to start the count.">
          {boards.most_favorited.map((entry) => (
            <PromptRow key={entry.path} entry={entry}
                       stat={count(entry.favorites, 'favorite', 'favorites')} />
          ))}
        </Board>

        <Board icon="shuffle" title="Most remixed"
               empty="No remixes yet — save a copy of a prompt to make the first one.">
          {boards.most_remixed.map((entry) => (
            <PromptRow key={entry.path} entry={entry}
                       stat={count(entry.remixes, 'remix', 'remixes')} />
          ))}
        </Board>

        <Board icon="edit" title="Top authors" empty="No published prompts yet.">
          {boards.top_authors.map((entry) => (
            <UserRow key={entry.username} name={entry.name}
                     stat={count(entry.prompts, 'prompt in the library', 'prompts in the library')} />
          ))}
        </Board>

        <Board icon="users" title="Top contributors" empty="No accepted suggestions yet.">
          {boards.top_contributors.map((entry) => (
            <UserRow key={entry.username} name={entry.name}
                     stat={count(entry.accepted, 'accepted suggestion', 'accepted suggestions')} />
          ))}
        </Board>
      </div>
    </div>
  )
}

function Board({ icon, title, empty, children }) {
  const rows = React.Children.toArray(children)
  return (
    <section className="card activity-col">
      <h2><Icon name={icon} size={17} /> {title}</h2>
      {rows.length === 0 && <div className="muted small">{empty}</div>}
      <ol className="plain-list ranked">{rows}</ol>
    </section>
  )
}

function PromptRow({ entry, stat }) {
  return (
    <li>
      <Link to={`/prompt/${entry.path}`} className="history-message">{entry.title}</Link>
      <span className="history-meta">{entry.category} · {stat}</span>
    </li>
  )
}

function UserRow({ name, stat }) {
  return (
    <li>
      <span className="history-message">{name}</span>
      <span className="history-meta">{stat}</span>
    </li>
  )
}

const count = (n, one, many) => `${n} ${n === 1 ? one : many}`

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleDateString()
}
