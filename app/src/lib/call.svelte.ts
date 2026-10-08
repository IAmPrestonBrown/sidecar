import { invoke } from '@tauri-apps/api/core'
import { get, inTauri, post } from './api'
import { app } from './state.svelte'
import type { ActiveCall } from './types'

const POLL_MS = 1500
const LIVE = new Set(['starting', 'ready', 'ending'])

/** The live call, polled from the engine while one is running. */
class CallState {
  current = $state<ActiveCall | null>(null)
  quitBlocked = $state(false)
  private timer: ReturnType<typeof setTimeout> | undefined
  private opened = ''

  get live(): boolean {
    return !!this.current && LIVE.has(this.current.state)
  }

  async refresh(): Promise<void> {
    const before = this.current?.state
    this.current = await get<ActiveCall | null>('/call')
    const now = this.current?.state
    if (inTauri()) await invoke('set_call_active', { active: this.live })
    if (this.current?.state === 'ready' && this.current.url !== this.opened) await this.showWindow()
    if (before && before !== now && (now === 'ended' || now === 'failed')) app.changed()
    clearTimeout(this.timer)
    if (this.live) this.timer = setTimeout(() => this.refresh().catch(() => {}), POLL_MS)
  }

  async start(personId: string, minutes: number, notes: string): Promise<void> {
    this.current = await post<ActiveCall>(`${app.base}/calls/start`, {
      person_id: personId,
      minutes,
      notes,
    })
    this.opened = ''
    await this.refresh()
  }

  async end(): Promise<void> {
    this.current = await post<ActiveCall>('/call/end')
    await this.refresh()
  }

  async showWindow(): Promise<void> {
    const call = this.current
    if (!call?.url) return
    this.opened = call.url
    if (inTauri()) {
      await invoke('open_call_window', { url: call.url, title: `Call with ${call.person_name}` })
    } else {
      window.open(call.url, 'sidecar-call')
    }
  }
}

export const call = new CallState()
