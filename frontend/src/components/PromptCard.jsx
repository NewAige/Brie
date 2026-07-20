import React from 'react'
import { Link } from 'react-router-dom'
import StatusBadge from './StatusBadge.jsx'
import LevelBadge from './LevelBadge.jsx'
import Icon from './Icon.jsx'

// The title's ::after overlay makes the whole card clickable; tags sit above
// it (z-index) so they stay independently clickable.
export default function PromptCard({ prompt, onTagClick }) {
  return (
    <div className={`card prompt-card ${prompt.status !== 'approved' ? 'card-muted' : ''}`}>
      <div className="card-head">
        <Link className="card-title" to={`/prompt/${prompt.path}`}>
          {prompt.title}
        </Link>
        <span className="card-badges">
          <LevelBadge level={prompt.level} owner={prompt.owner} compact />
          <StatusBadge status={prompt.status} />
        </span>
      </div>
      {prompt.intended_use && <p className="card-sub">{prompt.intended_use}</p>}
      <div className="card-foot">
        <span className="category-label">
          <Icon name="folder" size={13} /> {prompt.category}
        </span>
        <span className="tags">
          {prompt.tags.map((tag) => (
            <button key={tag} className="tag" onClick={() => onTagClick?.(tag)}>
              {tag}
            </button>
          ))}
        </span>
      </div>
    </div>
  )
}
