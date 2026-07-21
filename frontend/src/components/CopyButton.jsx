import React, { useRef, useState } from 'react'
import { api } from '../api.js'
import Icon from './Icon.jsx'

// Shared clipboard write with a fallback for non-HTTPS dev setups. Throws on
// failure so callers can show their own "copy failed" state.
export async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(ta)
  if (!ok) throw new Error('execCommand failed')
}

// THE feature (spec §4): copies the prompt body only — the backend already
// stripped the YAML front-matter, so `text` is exactly what gets copied.
export default function CopyButton({ text, path, large }) {
  const [state, setState] = useState('idle') // idle | copied | failed
  const timer = useRef(null)

  const flash = (next) => {
    setState(next)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setState('idle'), 2000)
  }

  const copy = async () => {
    try {
      await copyToClipboard(text)
      flash('copied')
      api.logCopy(path)
    } catch {
      flash('failed')
    }
  }

  return (
    <button
      className={`btn btn-primary ${large ? 'btn-large' : ''} ${state === 'copied' ? 'btn-success' : ''}`}
      onClick={copy}
      title="Copy the prompt text to your clipboard"
    >
      {state === 'copied' ? (
        <><Icon name="check" size={16} /> Copied</>
      ) : state === 'failed' ? (
        'Copy failed — select manually'
      ) : (
        <><Icon name="copy" size={16} /> Copy prompt</>
      )}
    </button>
  )
}
