import { useEffect, useRef } from 'react'

type Callback = () => void

export function useInterval(callback: Callback, delay: number | null) {
  const savedCallback = useRef<Callback>(() => {})

  useEffect(() => {
    savedCallback.current = callback
  }, [callback])

  useEffect(() => {
    if (delay === null) return

    const id = setInterval(() => {
      savedCallback.current()
    }, delay)

    return () => clearInterval(id)
  }, [delay])
}
