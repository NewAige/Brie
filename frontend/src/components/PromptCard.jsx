import React from 'react'
import { Link } from 'react-router-dom'
import StatusBadge from './StatusBadge.jsx'

export default function PromptCard({ prompt, onTagClick }) {
  return (
    <div className={`card prompt-card ${prompt.status !== 'approved' ? 'card-muted' : ''}`}>
      <div className="card-head">
        <Link className="card-title" to={`/prompt/${prompt.path}`}>
          {prompt.title}
        </Link>
        <StatusBadge status={prompt.status} />
      </div>
      {prompt.intended_use && <p className="card-sub">{prompt.intended_use}</p>}
      <div className="card-foot">
        <span className="category-label">{prompt.category}</span>
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
