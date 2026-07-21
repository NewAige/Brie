import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import Icon from './Icon.jsx'

// Star toggle shared by the library table rows and the prompt detail page.
//
// Optimistic: the star flips immediately and rolls back if the request fails,
// because marking is a low-stakes personal bookmark — waiting on a round trip
// to redraw an icon feels broken. `onChange` lets a parent (the Library page
// filtered to favourites) drop the row once it is unmarked.
export default function FavoriteButton({ path, favorited, onChange, large = false }) {
  const [marked, setMarked] = useState(favorited)
  const [busy, setBusy] = useState(false)

  // The same card can be reused for a different prompt as filters change, and
  // a refetch can bring a truer value than our optimistic guess.
  useEffect(() => setMarked(favorited), [favorited, path])

  const toggle = async (e) => {
    // Cards make their whole surface a link; starring must not navigate.
    e.preventDefault()
    e.stopPropagation()
    if (busy) return
    const next = !marked
    setMarked(next)
    setBusy(true)
    try {
      await api.setFavorite(path, next)
      onChange?.(path, next)
    } catch {
      setMarked(!next)
    } finally {
      setBusy(false)
    }
  }

  const label = marked ? 'Remove from favourites' : 'Save to favourites'
  return (
    <button
      type="button"
      className={`fav-btn ${marked ? 'fav-btn-on' : ''} ${large ? 'btn' : ''}`}
      onClick={toggle}
      aria-pressed={marked}
      title={label}
      aria-label={large ? undefined : label}
    >
      <Icon name="star" size={large ? 16 : 15} filled={marked} />
      {large && <span>{marked ? 'Favourited' : 'Favourite'}</span>}
    </button>
  )
}
