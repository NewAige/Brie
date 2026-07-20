import React, { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api.js'
import { UserContext } from './hooks.js'
import Activity from './pages/Activity.jsx'
import AdminUsers from './pages/AdminUsers.jsx'
import Browse from './pages/Browse.jsx'
import Drafts from './pages/Drafts.jsx'
import History from './pages/History.jsx'
import Login from './pages/Login.jsx'
import NewPrompt from './pages/NewPrompt.jsx'
import PromptDetail from './pages/PromptDetail.jsx'
import Suggestions from './pages/Suggestions.jsx'
import Icon from './components/Icon.jsx'
import Logo from './components/Logo.jsx'

const ROLE_LABELS = {
  browser: 'Browser',
  contributor: 'Contributor',
  approver: 'Bank Approver',
  admin: 'Admin',
}

const initials = (name = '') =>
  name
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('') || '?'

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

  if (checking) {
    return (
      <div className="center-screen">
        <div className="spinner-row"><span className="spinner" /> Loading…</div>
      </div>
    )
  }
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
              <Logo size={30} className="brand-logo" /> Brie
            </NavLink>
            <nav className="nav">
              <NavLink to="/" end><Icon name="folder" size={16} /> Library</NavLink>
              {user.role !== 'browser' && <NavLink to="/drafts"><Icon name="edit" size={16} /> My drafts</NavLink>}
              <NavLink to="/suggestions"><Icon name="inbox" size={16} /> Suggestions</NavLink>
              <NavLink to="/activity"><Icon name="activity" size={16} /> Activity</NavLink>
              {user.role === 'admin' && <NavLink to="/admin"><Icon name="users" size={16} /> Users</NavLink>}
            </nav>
            <div className="userbox">
              <div className="user-id">
                <span className="avatar" aria-hidden="true">{initials(user.full_name || user.username)}</span>
                <span className="user-meta">
                  <span className="user-name">{user.full_name}</span>
                  <span className={`role-chip role-${user.role}`}>{ROLE_LABELS[user.role] || user.role}</span>
                </span>
              </div>
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
            <Route path="/admin" element={<AdminUsers />} />
            <Route path="*" element={<div className="empty">Page not found.</div>} />
          </Routes>
        </main>
      </div>
    </UserContext.Provider>
  )
}
