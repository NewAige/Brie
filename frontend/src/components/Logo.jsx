import React from 'react'

/* Brie brand mark — a clock wheel with one wedge lifted out (the brie
   slice), plus minimal hour / minute hands in the wheel and a thin
   second hand carrying the wedge. Pure inline SVG: no external assets. */

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
      {/* Wheel body — full circle minus a 45° gap at the top right */}
      <path fill={TEAL} d="M50 50 L50 12 A38 38 0 1 0 76.87 23.13 Z" />

      {/* Hour hand (short, heavy) */}
      <line x1="50" y1="50" x2="36.5" y2="59" stroke={LIGHT} strokeWidth="5.5" strokeLinecap="round" />
      {/* Minute hand (long, heavy) */}
      <line x1="50" y1="50" x2="37" y2="27.5" stroke={LIGHT} strokeWidth="5.5" strokeLinecap="round" />

      {/* The lifted wedge — the extracted 45° slice, nudged up-right */}
      <g transform="translate(3.5, -3.5)">
        <path fill={NAVY} d="M50 50 L76.87 23.13 A38 38 0 0 0 50 12 Z" />
        {/* Second hand (thin) running through the wedge, tipped with a node */}
        <line x1="50" y1="50" x2="59.5" y2="27.5" stroke={LIGHT} strokeWidth="2.4" strokeLinecap="round" />
        <circle cx="59.5" cy="27.5" r="3.4" fill={LIGHT} />
      </g>

      {/* Central axis pin */}
      <circle cx="50" cy="50" r="5.5" fill={LIGHT} />
      <circle cx="50" cy="50" r="2.1" fill={NAVY} />
    </svg>
  )
}
