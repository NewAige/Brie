import React from 'react'

export default function Login() {
  const error = new URLSearchParams(window.location.search).get('error')
  return (
    <div className="center-screen">
      <div className="login-card">
        <div className="brand brand-large">
          <span className="brand-mark">¶</span> Prompt Library
        </div>
        <p className="muted">
          Browse, search and copy approved AI prompts — and suggest improvements
          that go through review before publication.
        </p>
        {error && (
          <div className="alert alert-error">
            Sign-in didn’t complete ({error}). Please try again.
          </div>
        )}
        <a className="btn btn-primary btn-block" href="/auth/login">
          Sign in with your bank credentials
        </a>
        <p className="muted small">
          You’ll sign in through the internal git service using your normal
          network account. This app never sees your password.
        </p>
      </div>
    </div>
  )
}
