import React from 'react'
import Icon from '../components/Icon.jsx'
import Logo from '../components/Logo.jsx'

export default function Login() {
  const error = new URLSearchParams(window.location.search).get('error')
  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="brand brand-large brand-stacked">
          <Logo size={72} className="brand-logo" />
          <span className="brand-name">Brie</span>
          <span className="brand-tagline">Prompt Library</span>
        </div>
        <ul className="login-points">
          <li><Icon name="shield" size={16} /> Every change reviewed before publication</li>
        </ul>
        {error && (
          <div className="alert alert-error">
            Sign-in didn’t complete ({error}). Please try again.
          </div>
        )}
        <a className="btn btn-primary btn-large btn-block" href="/auth/login">
          <Icon name="lock" size={17} /> Sign in
        </a>
      </div>
    </div>
  )
}
