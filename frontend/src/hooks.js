import { createContext, useContext, useEffect, useState } from 'react'
import { Unauthorized } from './api.js'

export const UserContext = createContext(null)
export const useUser = () => useContext(UserContext)

// Run an async load; flip to the sign-in screen on 401.
export function useAsyncData(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    loader()
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((err) => {
        if (!alive) return
        if (err instanceof Unauthorized) window.location.href = '/'
        else setState({ data: null, error: err.message, loading: false })
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
