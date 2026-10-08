import { invoke } from '@tauri-apps/api/core'

interface EngineInfo {
  port: number
  token: string
  error: string | null
}

export class ApiError extends Error {
  status: number
  fields: { field: string; message: string }[]

  constructor(status: number, message: string, fields: { field: string; message: string }[] = []) {
    super(message)
    this.status = status
    this.fields = fields
  }
}

let base = ''
let token = ''

const HEALTH_TIMEOUT_MS = 30000
const HEALTH_POLL_MS = 250

export function inTauri(): boolean {
  return '__TAURI_INTERNALS__' in window
}

/** Finds the engine and waits until it answers its health check. */
export async function connect(): Promise<void> {
  if (inTauri()) {
    const info = await invoke<EngineInfo>('engine_info')
    if (info.error) throw new Error(info.error)
    base = `http://127.0.0.1:${info.port}`
    token = info.token
  } else {
    base = import.meta.env.VITE_ENGINE_URL ?? 'http://127.0.0.1:8770'
    token = import.meta.env.VITE_ENGINE_TOKEN ?? ''
  }
  const deadline = Date.now() + HEALTH_TIMEOUT_MS
  let lastError: unknown = null
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/health`)
      if (res.ok) return
    } catch (err) {
      lastError = err
    }
    await new Promise((r) => setTimeout(r, HEALTH_POLL_MS))
  }
  throw new Error(`The engine did not start within 30 seconds. ${lastError ?? ''}`)
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    method,
    headers: {
      'X-Sidecar-Token': token,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    let fields: { field: string; message: string }[] = []
    try {
      const data = await res.json()
      detail = data.detail ?? detail
      fields = data.errors ?? []
    } catch {
      // The body was not JSON; the status text is used instead.
    }
    throw new ApiError(res.status, detail, fields)
  }
  return (await res.json()) as T
}

/** A URL the webview can load directly, such as audio, with the token in the query. */
export function mediaUrl(path: string): string {
  return `${base}${path}?token=${encodeURIComponent(token)}`
}

export const get = <T>(path: string) => api<T>('GET', path)
export const post = <T>(path: string, body?: unknown) => api<T>('POST', path, body ?? {})
export const patch = <T>(path: string, body: unknown) => api<T>('PATCH', path, body)
export const put = <T>(path: string, body: unknown) => api<T>('PUT', path, body)
export const del = <T>(path: string) => api<T>('DELETE', path)
