import React, { useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { copyToClipboard } from './CopyButton.jsx'
import { parseImport } from '../aiImport.js'

// Two-step "draft it with AI" helper shown on the New prompt and Suggest an
// edit forms. Step 1 copies ready-made instructions the user pastes into their
// own approved AI assistant; step 2 imports the structured result that
// assistant hands back and fills in the form. The app never calls a model
// itself (spec §2) — the user is the courier in both directions.
//
// `buildInstructions` is called at click time so the instructions always
// reflect what's currently typed into the form. `onImport` receives the
// normalized values from aiImport.parseImport.
export default function AiAssist({ expectedType, buildInstructions, onImport }) {
  const [open, setOpen] = useState(false)
  const [copyState, setCopyState] = useState('idle') // idle | copied | failed
  const [pasted, setPasted] = useState('')
  const [error, setError] = useState(null)
  const [imported, setImported] = useState(false)
  const timer = useRef(null)

  const copyInstructions = async () => {
    try {
      await copyToClipboard(buildInstructions())
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setCopyState('idle'), 2000)
  }

  const doImport = () => {
    setError(null)
    try {
      onImport(parseImport(pasted, expectedType))
      setPasted('')
      setImported(true)
    } catch (err) {
      setImported(false)
      setError(err.message)
    }
  }

  return (
    <div className="ai-assist">
      <button
        type="button"
        className="btn btn-quiet ai-assist-toggle"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <Icon name="spark" size={16} /> Draft it with AI
        <Icon name={open ? 'chevron-down' : 'chevron'} size={14} />
      </button>

      {open && (
        <div className="ai-assist-body">
          <p className="muted small">
            <strong>Step 1.</strong> Copy the instructions below into your
            approved AI assistant. It will ask a few questions to understand
            what you need, then hand back a block of structured text.
          </p>
          <button type="button" className="btn" onClick={copyInstructions}>
            {copyState === 'copied' ? (
              <><Icon name="check" size={16} /> Copied — paste it into your assistant</>
            ) : copyState === 'failed' ? (
              'Copy failed — try again'
            ) : (
              <><Icon name="copy" size={16} /> Copy AI instructions</>
            )}
          </button>

          <p className="muted small">
            <strong>Step 2.</strong> When you&apos;re happy with the assistant&apos;s
            final answer, paste the whole structured block here and it will fill
            in the form. You can still edit everything before sending.
          </p>
          <textarea
            className="editor-area ai-assist-paste"
            value={pasted}
            onChange={(e) => { setPasted(e.target.value); setImported(false) }}
            rows={5}
            spellCheck="false"
            placeholder={'Paste the assistant\'s result here — the block starting with { "type": … }'}
          />
          {error && <div className="alert alert-error">{error}</div>}
          {imported && (
            <div className="alert alert-success">
              Filled in from the AI result — review it below before sending.
            </div>
          )}
          <div>
            <button type="button" className="btn" onClick={doImport} disabled={!pasted.trim()}>
              <Icon name="inbox" size={16} /> Fill in the form
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
