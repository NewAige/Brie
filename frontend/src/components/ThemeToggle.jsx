import React, { useEffect, useState } from 'react'
import Icon from './Icon.jsx'

// The saved value is a plain display preference ("dark" / "light") — nothing
// token-like, so localStorage is fine here. index.html applies it before the
// first paint; this component only has to keep <html data-theme> and the
// stored value in sync when the user toggles.
const STORAGE_KEY = 'brie-theme'

export default function ThemeToggle() {
  const [dark, setDark] = useState(
    () => document.documentElement.dataset.theme === 'dark'
  )

  useEffect(() => {
    if (dark) document.documentElement.dataset.theme = 'dark'
    else delete document.documentElement.dataset.theme
    try {
      localStorage.setItem(STORAGE_KEY, dark ? 'dark' : 'light')
    } catch {
      /* private browsing — the toggle still works for this visit */
    }
  }, [dark])

  const label = dark ? 'Switch to light mode' : 'Switch to dark mode'
  return (
    <button
      className="icon-btn theme-toggle"
      onClick={() => setDark((d) => !d)}
      aria-label={label}
      title={label}
    >
      <Icon name={dark ? 'sun' : 'moon'} size={18} />
    </button>
  )
}
