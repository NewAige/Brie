import React from 'react'
import { Link } from 'react-router-dom'
import LevelBadge from './LevelBadge.jsx'
import Icon from './Icon.jsx'
import FavoriteButton from './FavoriteButton.jsx'

// The title's ::after overlay makes the whole card clickable; tags and the
// favourite star sit above it (z-index) so they stay independently clickable.
export default function PromptCard({ prompt, onTagClick, onFavoriteChange }) {
  return (
    <div className="card prompt-card">
      <div className="card-head">
        <Link className="card-title" to={`/prompt/${prompt.path}`}>
          {prompt.title}
        </Link>
        <span className="card-badges">
          <LevelBadge level={prompt.level} owner={prompt.owner} compact />
          <FavoriteButton
            path={prompt.path}
            favorited={prompt.favorited}
            onChange={onFavoriteChange}
          />
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
