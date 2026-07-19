import React, { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api.js'
import { UserContext } from './hooks.js'
import Activity from './pages/Activity.jsx'
import Browse from './pages/Browse.jsx'
import Drafts from './pages/Drafts.jsx'
import History from './pages/History.jsx'
import Login from './pages/Login.jsx'
import NewPrompt from './pages/NewPrompt.jsx'
import PromptDetail from './pages/PromptDetail.jsx'
import Suggestions from './pages/Suggestions.jsx'

const ROLE_LABELS = {
  browser: 'Browser',
  contributor: 'Contributor',
  approver: 'Bank Approver',
  admin: 'Admin',
}

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecking(false))
  }, [])

  if (checking) return <div className="center-screen muted">Loading…</div>
  if (!user) return <Login />

  const logout = async () => {
    await api.logout().catch(() => {})
    window.location.href = '/'
  }

  return (
    <UserContext.Provider value={user}>
      <div className="shell">
        <header className="topbar">
          <div className="topbar-inner">
            <NavLink to="/" className="brand">
              <span className="brand-mark">¶</span> Prompt Library
            </NavLink>
            <nav className="nav">
              <NavLink to="/" end>Library</NavLink>
              {user.role !== 'browser' && <NavLink to="/drafts">My drafts</NavLink>}
              <NavLink to="/suggestions">Suggestions</NavLink>
              <NavLink to="/activity">Activity</NavLink>
            </nav>
            <div className="userbox">
              <span className="user-name">{user.full_name}</span>
              <span className={`role-chip role-${user.role}`}>{ROLE_LABELS[user.role] || user.role}</span>
              <button className="btn btn-quiet" onClick={logout}>Sign out</button>
            </div>
          </div>
        </header>
        <main className="content">
          <Routes>
            <Route path="/" element={<Browse />} />
            <Route path="/new" element={<NewPrompt />} />
            <Route path="/drafts" element={<Drafts />} />
            <Route path="/prompt/*" element={<PromptDetail />} />
            <Route path="/history/*" element={<History />} />
            <Route path="/suggestions" element={<Suggestions />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="*" element={<div className="empty">Page not found.</div>} />
          </Routes>
        </main>
      </div>
    </UserContext.Provider>
  )
}
