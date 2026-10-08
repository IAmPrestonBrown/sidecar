import { get, post } from './api'
import type { GmailStatus } from './types'

const POLL_MS = 1500

/** The one Gmail account, shared by every project. */
class GmailState {
  status = $state<GmailStatus | null>(null)
  error = $state('')
  private timer: ReturnType<typeof setTimeout> | undefined

  get connected(): boolean {
    return !!this.status?.connected
  }

  async refresh(): Promise<void> {
    clearTimeout(this.timer)
    try {
      this.status = await get<GmailStatus>('/gmail')
    } catch (e) {
      this.error = String(e)
      return
    }
    // Watch for the browser sign-in to finish.
    if (this.status.connecting) this.timer = setTimeout(() => this.refresh(), POLL_MS)
  }

  async connect(): Promise<void> {
    this.error = ''
    try {
      await post('/gmail/connect')
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e)
    }
    await this.refresh()
  }

  async disconnect(): Promise<void> {
    this.status = await post<GmailStatus>('/gmail/disconnect')
  }
}

export const gmail = new GmailState()
