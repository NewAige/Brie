import React from 'react'

/* Brie brand mark — a minimal clock face: solid teal disc with a heavy
   hour and minute hand, a thin second hand, and a central axis pin.
   Pure inline SVG: no external assets. */

const TEAL = '#006F51'
const NAVY = '#20333F'
const LIGHT = '#F5F7F8'

export default function Logo({ size = 32, className }) {
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label="Brie"
    >
      <circle cx="50" cy="50" r="40" fill={TEAL} />

      {/* Hour hand (short, heavy) — just past 11 (11:05) */}
      <line x1="50" y1="50" x2="42" y2="35" stroke={LIGHT} strokeWidth="6" strokeLinecap="round" />
      {/* Minute hand (long, heavy) — on the 1 (5 minutes) */}
      <line x1="50" y1="50" x2="63.5" y2="26.5" stroke={LIGHT} strokeWidth="6" strokeLinecap="round" />
      {/* Second hand (thin) — toward 7, tipped with a node */}
      <line x1="50" y1="50" x2="36.5" y2="73.5" stroke={LIGHT} strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="36.5" cy="73.5" r="3.2" fill={LIGHT} />

      {/* Central axis pin */}
      <circle cx="50" cy="50" r="5.5" fill={LIGHT} />
      <circle cx="50" cy="50" r="2.1" fill={NAVY} />
    </svg>
  )
}
