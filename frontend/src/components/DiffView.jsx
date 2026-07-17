import React from 'react'

// Minimal unified-diff renderer: color added/removed lines, mute the headers.
export default function DiffView({ diff }) {
  if (!diff || !diff.trim()) return <div className="muted small">No changes.</div>
  return (
    <pre className="diff">
      {diff.split('\n').map((line, i) => {
        let cls = 'diff-ctx'
        if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@') || line.startsWith('diff ') || line.startsWith('index ')) {
          cls = 'diff-meta'
        } else if (line.startsWith('+')) cls = 'diff-add'
        else if (line.startsWith('-')) cls = 'diff-del'
        return (
          <div key={i} className={cls}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}
