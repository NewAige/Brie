import React from 'react'
import Icon from '../components/Icon.jsx'

export default function Login() {
  const error = new URLSearchParams(window.location.search).get('error')
  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="brand brand-large">
          <span className="brand-mark">¶</span> Prompt Library
        </div>
        <p className="muted login-tagline">
          Your team&apos;s approved AI prompts — searchable, copyable, and
          reviewed before they reach you.
        </p>
        <ul className="login-points">
          <li><Icon name="search" size={16} /> Browse and search the full library</li>
          <li><Icon name="copy" size={16} /> Copy a prompt in one click</li>
          <li><Icon name="shield" size={16} /> Every change reviewed before publication</li>
        </ul>
        {error && (
          <div className="alert alert-error">
            Sign-in didn’t complete ({error}). Please try again.
          </div>
        )}
        <a className="btn btn-primary btn-large btn-block" href="/auth/login">
          <Icon name="lock" size={17} /> Sign in with your bank credentials
        </a>
        <p className="muted small">
          You’ll sign in through the internal git service using your normal
          network account. This app never sees your password.
        </p>
      </div>
    </div>
  )
}
