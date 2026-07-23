import React, { useRef, useState } from 'react'
import { copyToClipboard } from './CopyButton.jsx'
import Icon from './Icon.jsx'

// Side-by-side reading view of a suggestion: the prompt as it is today next
// to the prompt as suggested, with changed lines paired and highlighted, and
// a copy button on each version so a reviewer can paste either one into an
// external AI tool and try it before deciding. Bodies only — the backend
// strips front-matter with the same split the copy button uses (spec §4).

export default function CompareView({ files }) {
  const showPaths = files.length > 1
  return (
    <div>
      {files.map((f) => (
        <div key={f.path}>
          {showPaths && (
            <div className="hunk-file">
              {f.path}
              {f.status === 'added' && <span className="own-chip">new prompt</span>}
              {f.status === 'removed' && <span className="own-chip">removed</span>}
            </div>
          )}
          {f.details_changed && (
            <p className="muted small compare-note">
              This suggestion also changes the prompt’s details (title, tags, …),
              which aren’t part of the text below — the “Changes” view shows those.
            </p>
          )}
          <ComparePanes file={f} />
        </div>
      ))}
    </div>
  )
}

function ComparePanes({ file }) {
  const current = file.current ? file.current.body : null
  const suggested = file.suggested ? file.suggested.body : null
  const rows = pairRows(
    current === null ? [] : current.split('\n'),
    suggested === null ? [] : suggested.split('\n'),
  )
  return (
    <div className="compare">
      <div className="compare-head">
        <span>Current{current === null && ' — nothing yet'}</span>
        {!!current && <CopySide text={current} label="Copy current" />}
      </div>
      <div className="compare-head">
        <span>Suggested{suggested === null && ' — prompt removed'}</span>
        {!!suggested && <CopySide text={suggested} label="Copy suggested" primary />}
      </div>
      {rows.map((row, i) => {
        const marks = row.changed && row.l !== null && row.r !== null
          ? markWords(row.l, row.r)
          : null
        return (
          <React.Fragment key={i}>
            <Cell line={row.l} segs={marks && marks[0]} cls={row.changed ? 'compare-del' : ''} />
            <Cell line={row.r} segs={marks && marks[1]} cls={row.changed ? 'compare-add' : ''} />
          </React.Fragment>
        )
      })}
    </div>
  )
}

function Cell({ line, segs, cls }) {
  if (line === null) return <div className="compare-line compare-gap" />
  return (
    <div className={`compare-line ${cls}`}>
      {segs && segs.length
        ? segs.map((s, i) => (s.m ? <mark key={i}>{s.t}</mark> : s.t))
        : line || ' '}
    </div>
  )
}

// Deliberately not CopyButton: no api.logCopy here, because copy counts feed
// the most-copied leaderboard and should reflect real prompt use, not
// review-time test copies.
function CopySide({ text, label, primary }) {
  const [state, setState] = useState('idle') // idle | copied | failed
  const timer = useRef(null)
  const copy = async () => {
    try {
      await copyToClipboard(text)
      setState('copied')
    } catch {
      setState('failed')
    }
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setState('idle'), 2000)
  }
  return (
    <button
      className={`btn compare-copy ${primary ? 'btn-primary' : 'btn-quiet'} ${state === 'copied' ? 'btn-success' : ''}`}
      onClick={copy}
      title="Copy this version to try it in your AI tool"
    >
      {state === 'copied' ? (
        <><Icon name="check" size={14} /> Copied</>
      ) : state === 'failed' ? (
        'Copy failed'
      ) : (
        <><Icon name="copy" size={14} /> {label}</>
      )}
    </button>
  )
}

// ---- alignment ------------------------------------------------------------
//
// Line-level longest-common-subsequence, so unchanged text sits level in both
// columns and each edit pairs up with what it replaces. Inputs are
// prompt-sized markdown; past the cap we skip alignment rather than lock the
// tab up, and the two columns render plainly.

const MAX_LINE_CELLS = 250_000
const MAX_WORD_CELLS = 10_000

function pairRows(a, b) {
  const rows = []
  if (a.length * b.length > MAX_LINE_CELLS) {
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      rows.push({ l: i < a.length ? a[i] : null, r: i < b.length ? b[i] : null, changed: false })
    }
    return rows
  }
  // Pair up each run of removed/added lines between two unchanged ones.
  let dels = []
  let inss = []
  const flush = () => {
    for (let k = 0; k < Math.max(dels.length, inss.length); k++) {
      rows.push({
        l: k < dels.length ? dels[k] : null,
        r: k < inss.length ? inss[k] : null,
        changed: true,
      })
    }
    dels = []
    inss = []
  }
  for (const [tag, l, r] of lcsOps(a, b)) {
    if (tag === 'equal') {
      flush()
      rows.push({ l, r, changed: false })
    } else if (tag === 'del') dels.push(l)
    else inss.push(r)
  }
  flush()
  return rows
}

// Word-level marks inside one paired changed row, so the reviewer sees which
// words moved, not just that the line did. Null (no marks) past the cap.
function markWords(l, r) {
  const ta = l.split(/(\s+)/).filter(Boolean)
  const tb = r.split(/(\s+)/).filter(Boolean)
  if (ta.length * tb.length > MAX_WORD_CELLS) return null
  const left = []
  const right = []
  for (const [tag, x, y] of lcsOps(ta, tb)) {
    if (tag === 'equal') {
      left.push({ t: x, m: false })
      right.push({ t: y, m: false })
    } else if (tag === 'del') left.push({ t: x, m: true })
    else right.push({ t: y, m: true })
  }
  return [mergeSegs(left), mergeSegs(right)]
}

function mergeSegs(segs) {
  const out = []
  for (const s of segs) {
    if (out.length && out[out.length - 1].m === s.m) out[out.length - 1].t += s.t
    else out.push({ ...s })
  }
  return out
}

// Classic LCS over two token arrays, emitted as ['equal'|'del'|'ins', a, b]
// steps in order. Callers cap input sizes; the table is a flat Uint32Array.
function lcsOps(a, b) {
  const n = a.length
  const m = b.length
  const width = m + 1
  const len = new Uint32Array((n + 1) * width)
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      len[i * width + j] = a[i] === b[j]
        ? len[(i + 1) * width + j + 1] + 1
        : Math.max(len[(i + 1) * width + j], len[i * width + j + 1])
    }
  }
  const ops = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) ops.push(['equal', a[i++], b[j++]])
    else if (len[(i + 1) * width + j] >= len[i * width + j + 1]) ops.push(['del', a[i++], null])
    else ops.push(['ins', null, b[j++]])
  }
  while (i < n) ops.push(['del', a[i++], null])
  while (j < m) ops.push(['ins', null, b[j++]])
  return ops
}
