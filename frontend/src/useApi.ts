import { useEffect, useState } from 'react'
import { buildUrl, getUrl, type Params } from './api'

export interface ApiState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

interface Result<T> {
  url: string
  data: T | null
  error: string | null
}

/** Fetches whenever the URL (path + params) changes. Keeps the previous data while reloading
 *  so charts hold their frame instead of flashing (dataviz: "refetch keeps the frame"). */
export function useApi<T>(path: string | null, params: Params = {}): ApiState<T> {
  const url = path ? buildUrl(path, params) : null
  const [result, setResult] = useState<Result<T> | null>(null)

  useEffect(() => {
    if (!url) return
    const controller = new AbortController()
    getUrl<T>(url, controller.signal)
      .then((data) => setResult({ url, data, error: null }))
      .catch((err: Error) => {
        if (err.name !== 'AbortError') setResult((prev) => ({ url, data: prev?.data ?? null, error: err.message }))
      })
    return () => controller.abort()
  }, [url])

  return {
    data: result?.data ?? null,
    error: result?.url === url ? result.error : null,
    loading: url !== null && result?.url !== url,
  }
}
