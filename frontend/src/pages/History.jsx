import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAsyncData } from '../hooks.js'
import { api } from '../api.js'
import CommitHistory from '../components/CommitHistory.jsx'

export default function History() {
  const path = decodeURIComponent(useLocation().pathname.replace(/^\/history\//, ''))
  const { data, error, loading } = useAsyncData(() => api.history(path), [path])

  return (
    <div className="detail">
      <div className="crumbs">
        <Link to="/">Library</Link> / <Link to={`/prompt/${path}`}>{path.split('/').pop()}</Link> /{' '}
        <span className="muted">history</span>
      </div>
      <h1>History</h1>
      <p className="muted">Every published change to this prompt: who, when, and what.</p>

      {loading && <div className="spinner-row"><span className="spinner" /> Loading…</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <CommitHistory commits={data} />
    </div>
  )
}
