import React from 'react'

// Tiny inline SVG icon set — keeps the app fully self-contained (spec §8:
// no external assets). Stroke-based, inherits `currentColor`, sized via CSS.
const PATHS = {
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.8-3.8" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </>
  ),
  check: <path d="m4.5 12.5 5 5 10-11" />,
  plus: <path d="M12 5v14M5 12h14" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  doc: (
    <>
      <path d="M6 2.8h8l4 4v14.4H6z" />
      <path d="M13.6 2.8v4.4H18M9 12h6M9 15.6h6" />
    </>
  ),
  edit: <path d="M4 20h4.5L19.6 8.9a2.1 2.1 0 0 0-3-3L5.5 17z" />,
  send: <path d="M21 3 3 10.5l7 3.5m11-11L13.5 21 10 14m11-11L10 14" />,
  users: (
    <>
      <circle cx="9" cy="8" r="3.4" />
      <path d="M2.8 20c.6-3.4 3.1-5.4 6.2-5.4s5.6 2 6.2 5.4" />
      <path d="M16 5.2a3.2 3.2 0 0 1 0 6M17.4 15c2.2.6 3.5 2.3 3.9 4.6" />
    </>
  ),
  shield: (
    <>
      <path d="M12 2.8 4.6 5.6v6c0 4.6 3 8 7.4 9.6 4.4-1.6 7.4-5 7.4-9.6v-6z" />
      <path d="m8.8 11.8 2.3 2.3 4.2-4.6" />
    </>
  ),
  lock: (
    <>
      <rect x="4.6" y="10.4" width="14.8" height="10" rx="2" />
      <path d="M8 10.4V7.6a4 4 0 0 1 8 0v2.8" />
    </>
  ),
  spark: <path d="M12 2.5 14.3 9l6.6 1-5 4.6 1.4 6.7L12 17.7l-5.3 3.6L8.1 14.6l-5-4.6 6.6-1z" />,
  activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  folder: <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2.4h8.4A1.5 1.5 0 0 1 21 8.9v9.6a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z" />,
  inbox: (
    <>
      <path d="M3.5 13.5 6 5h12l2.5 8.5v5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z" />
      <path d="M3.5 13.5H9a3 3 0 0 0 6 0h5.5" />
    </>
  ),
  chevron: <path d="m9 6 6 6-6 6" />,
  history: (
    <>
      <path d="M4 12a8 8 0 1 0 2.3-5.6L4 8.7" />
      <path d="M4 4.5v4.2h4.2M12 8v4.5l3 1.8" />
    </>
  ),
  trash: (
    <>
      <path d="M4.5 6.5h15M9.5 6.5V4.8a1.3 1.3 0 0 1 1.3-1.3h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
      <path d="M6.5 6.5 7.4 20h9.2l.9-13.5M10 10.5v6M14 10.5v6" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.6 2.5 3.9 5.5 3.9 9S14.6 18.5 12 21c-2.6-2.5-3.9-5.5-3.9-9S9.4 5.5 12 3z" />
    </>
  ),
}

export default function Icon({ name, size = 18, className = '' }) {
  const path = PATHS[name]
  if (!path) return null
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {path}
    </svg>
  )
}
