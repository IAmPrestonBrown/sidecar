<script lang="ts">
  import GmailCard from '../components/GmailCard.svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, patch, post } from '../lib/api'
  import { autosize } from '../lib/autosize'
  import { app } from '../lib/state.svelte'
  import type { EmailSettings, ProjectMeta } from '../lib/types'

  const TABS = [
    ['general', 'General'],
    ['email', 'Email'],
    ['sending', 'Sending'],
    ['coach', 'Coach'],
  ] as const
  type Tab = (typeof TABS)[number][0]

  const TEMPLATES: [keyof EmailSettings, string][] = [
    ['body_template', 'First email'],
    ['follow_up_template', 'Follow-up'],
    ['final_template', 'Final note'],
  ]
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const ACTIVITY: [string, string, string][] = [
    ['quiet', 'Quiet', 'A few cards per interview, only for important moments.'],
    ['balanced', 'Balanced', 'About one card every one to two minutes.'],
    ['active', 'Active', 'About one card a minute.'],
  ]

  const tab = $derived<Tab>(TABS.some(([t]) => t === app.route.id) ? (app.route.id as Tab) : 'general')

  let meta = $state<ProjectMeta | null>(null)
  let exported = $state<{ json: string; markdown: string } | null>(null)
  let saved = $state('')
  let error = $state('')
  let savedTimer: ReturnType<typeof setTimeout> | undefined

  $effect(() => {
    void app.version
    // Loading the templates first fills empty ones from the outreach brief.
    get(`${app.base}/outreach/templates`)
      .then(() => get<ProjectMeta>(app.base))
      .then((m) => (meta = m))
      .catch((e) => (error = String(e)))
  })

  async function save(fields: Record<string, unknown>) {
    error = ''
    try {
      meta = await patch<ProjectMeta>(app.base, fields)
      saved = 'Saved'
      clearTimeout(savedTimer)
      savedTimer = setTimeout(() => (saved = ''), 1500)
    } catch (e) {
      error = String(e)
    }
  }

  const num = (e: Event) => Number((e.currentTarget as HTMLInputElement).value)
  const text = (e: Event) => (e.currentTarget as HTMLInputElement).value
  const checked = (e: Event) => (e.currentTarget as HTMLInputElement).checked

  function toggleDay(day: number) {
    if (!meta) return
    const days = meta.sending.weekdays.includes(day)
      ? meta.sending.weekdays.filter((d) => d !== day)
      : [...meta.sending.weekdays, day].sort()
    save({ sending: { weekdays: days } })
  }

  function keyterms(e: Event) {
    const list = (e.currentTarget as HTMLTextAreaElement).value
      .split('\n')
      .map((t) => t.trim())
      .filter(Boolean)
    if (meta && list.join('\n') !== meta.coach.keyterms.join('\n')) save({ coach: { keyterms: list } })
  }

  async function exportProject() {
    exported = await post<{ json: string; markdown: string }>(`${app.base}/export`)
  }
</script>

<Toolbar title="Settings" subtitle={meta?.name ?? ''}>
  {#snippet actions()}
    {#if saved}<span class="muted">{saved}</span>{/if}
    <div class="segmented" role="tablist" aria-label="Settings sections">
      {#each TABS as [id, name] (id)}
        <button role="tab" aria-selected={tab === id} onclick={() => app.go('settings', id)}>{name}</button>
      {/each}
    </div>
  {/snippet}
</Toolbar>

<div class="body">
  {#if error}<div class="error-banner">{error}</div>{/if}
  {#if meta}
    {#if tab === 'general'}
      <section>
        <h2>Project</h2>
        <div class="group rows">
          <div class="row">
            <label for="pname">Name</label>
            <input id="pname" class="field" value={meta.name} onblur={(e) => save({ name: text(e) })} />
          </div>
          <div class="row">
            <span class="label">Folder</span>
            <span class="value">
              <span class="selectable path">{meta.path}</span>
              <button class="btn small" onclick={() => post(`${app.base}/reveal`)}>Show in Finder</button>
            </span>
          </div>
        </div>
        <p class="hint">Every record is a readable JSON or Markdown file in this folder.</p>
      </section>

      <section>
        <h2>Export</h2>
        <div class="group rows">
          <div class="row">
            <span class="label">Whole project</span>
            <span class="value">
              <button class="btn small" onclick={exportProject}>Export JSON and Markdown</button>
            </span>
          </div>
          {#if exported}
            <div class="row">
              <span class="label">Written to</span>
              <span class="value stack selectable path">
                <span>{exported.json}</span><span>{exported.markdown}</span>
              </span>
            </div>
          {/if}
        </div>
        <p class="hint">One file each, ready to paste or upload into ChatGPT or another tool.</p>
      </section>
    {:else if tab === 'email'}
      <section>
        <h2>Account</h2>
        <GmailCard />
        <p class="hint">One account for all projects. Its access is kept in the macOS Keychain.</p>
      </section>

      <section>
        <h2>Sender</h2>
        <div class="group rows">
          <div class="row">
            <label for="sender">Name</label>
            <input
              id="sender"
              class="field short"
              placeholder="Shown as the sender"
              value={meta.email.sender_name}
              onblur={(e) => save({ email: { sender_name: text(e) } })}
            />
          </div>
          <div class="row">
            <span class="label">Footer</span>
            <label class="check value"
              ><input
                type="checkbox"
                checked={meta.email.footer_enabled}
                onchange={(e) => save({ email: { footer_enabled: checked(e) } })}
              /> Add a postal address and opt-out line</label
            >
          </div>
          {#if meta.email.footer_enabled}
            <div class="row">
              <label for="addr">Postal address</label>
              <input
                id="addr"
                class="field"
                value={meta.email.postal_address}
                onblur={(e) => save({ email: { postal_address: text(e) } })}
              />
            </div>
            <div class="row">
              <label for="opt">Opt-out line</label>
              <input
                id="opt"
                class="field"
                value={meta.email.opt_out_line}
                onblur={(e) => save({ email: { opt_out_line: text(e) } })}
              />
            </div>
          {/if}
        </div>
        <p class="hint">
          Research requests don't need a footer. Turn it on if outreach ever promotes something.
        </p>
      </section>

      <section>
        <h2>Templates</h2>
        <div class="group rows">
          <div class="row">
            <label for="t-subject">Subject</label>
            <input
              id="t-subject"
              class="field"
              value={meta.email.subject_template}
              onblur={(e) => save({ email: { subject_template: text(e) } })}
            />
          </div>
          {#each TEMPLATES as [key, name] (key)}
            <div class="row top">
              <label for={`t-${key}`}>{name}</label>
              <textarea
                id={`t-${key}`}
                class="field template"
                rows="4"
                value={String(meta.email[key])}
                use:autosize={String(meta.email[key])}
                onblur={(e) => save({ email: { [key]: text(e) } })}></textarea>
            </div>
          {/each}
        </div>
        <p class="hint">
          <code>{'{first_name}'}</code>, <code>{'{organization}'}</code>, and
          <code>{'{optional_sentence}'}</code> are filled in for each person; an empty optional sentence removes
          its line. Changes apply to new drafts.
        </p>
      </section>
    {:else if tab === 'sending'}
      <section>
        <h2>Sending</h2>
        <div class="group rows">
          <div class="row">
            <span class="label">Send</span>
            <label class="check value"
              ><input
                type="checkbox"
                checked={meta.sending.active}
                onchange={(e) => save({ sending: { active: checked(e) } })}
              /> Send approved emails for this project</label
            >
          </div>
        </div>
        <p class="hint">
          Only emails you approved are sent, one at a time. Sending pauses during calls and while Sidecar is
          closed.
        </p>
      </section>

      <section>
        <h2>Pace</h2>
        <div class="group rows">
          <div class="row">
            <label for="cap">Daily limit</label>
            <span class="value">
              <input
                id="cap"
                class="field num-field"
                type="number"
                min="1"
                max="200"
                value={meta.sending.daily_cap}
                onchange={(e) => save({ sending: { daily_cap: num(e) } })}
              />
              <span class="muted">emails a day</span>
            </span>
          </div>
          <div class="row">
            <span class="label">Hours</span>
            <span class="value">
              <input
                class="field"
                type="time"
                aria-label="Start"
                value={meta.sending.window_start}
                onchange={(e) => save({ sending: { window_start: text(e) } })}
              />
              <span class="muted">to</span>
              <input
                class="field"
                type="time"
                aria-label="End"
                value={meta.sending.window_end}
                onchange={(e) => save({ sending: { window_end: text(e) } })}
              />
            </span>
          </div>
          <div class="row">
            <span class="label">Days</span>
            <span class="value days" role="group" aria-label="Sending days">
              {#each DAYS as name, i (name)}
                <button
                  class="day"
                  aria-pressed={meta.sending.weekdays.includes(i)}
                  onclick={() => toggleDay(i)}>{name}</button
                >
              {/each}
            </span>
          </div>
          <div class="row">
            <span class="label">Spacing</span>
            <span class="value">
              <input
                class="field num-field"
                type="number"
                min="1"
                aria-label="Minimum minutes between emails"
                value={meta.sending.min_gap_minutes}
                onchange={(e) => save({ sending: { min_gap_minutes: num(e) } })}
              />
              <span class="muted">to</span>
              <input
                class="field num-field"
                type="number"
                min="1"
                aria-label="Maximum minutes between emails"
                value={meta.sending.max_gap_minutes}
                onchange={(e) => save({ sending: { max_gap_minutes: num(e) } })}
              />
              <span class="muted">minutes apart</span>
            </span>
          </div>
        </div>
        <p class="hint">
          Hours and days follow each recipient's time zone when it is known, otherwise this Mac's.
        </p>
      </section>
    {:else}
      <section>
        <h2>Cards during calls</h2>
        <div class="group rows">
          {#each ACTIVITY as [value, name, detail] (value)}
            <label class="row choice">
              <input
                type="radio"
                name="activity"
                {value}
                checked={meta.coach.activity === value}
                onchange={() => save({ coach: { activity: value } })}
              />
              <span class="stack"><span>{name}</span><span class="muted">{detail}</span></span>
            </label>
          {/each}
        </div>
      </section>

      <section>
        <h2>Words to recognize</h2>
        <div class="group rows">
          <div class="row top">
            <label for="keyterms">Keyterms</label>
            <textarea
              id="keyterms"
              class="field template"
              rows="5"
              placeholder="One per line"
              value={meta.coach.keyterms.join('\n')}
              onblur={keyterms}></textarea>
          </div>
        </div>
        <p class="hint">
          Product names, jargon, and company names the transcription should get right. Used for this project's
          calls.
        </p>
      </section>
    {/if}
  {/if}
</div>

<style>
  .body {
    padding: 24px 24px 48px;
    max-width: 680px;
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  h2 {
    margin: 0 4px 2px;
    font-size: 13px;
    font-weight: 600;
  }
  .hint {
    margin: 2px 4px 0;
    color: var(--muted);
    font-size: 12px;
    line-height: 1.45;
  }
  .rows {
    display: flex;
    flex-direction: column;
  }
  .row {
    display: grid;
    grid-template-columns: 120px minmax(0, 1fr);
    align-items: center;
    gap: 12px;
    min-height: 44px;
    padding: 6px 14px;
  }
  .row + .row {
    border-top: 1px solid var(--sep-soft);
  }
  .row.top {
    align-items: start;
    padding-top: 10px;
    padding-bottom: 10px;
  }
  .row.top > label {
    padding-top: 5px;
  }
  .row > label,
  .row > .label {
    color: var(--text);
  }
  .value {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .choice {
    grid-template-columns: 20px minmax(0, 1fr);
    cursor: pointer;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .short {
    max-width: 260px;
  }
  .num-field {
    width: 64px;
  }
  .template {
    font-size: 13px;
    line-height: 1.5;
    overflow: hidden;
  }
  .check {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .path {
    overflow-wrap: anywhere;
    color: var(--muted);
  }
  .days {
    gap: 4px;
  }
  .day {
    min-width: 42px;
    height: 26px;
    border: 1px solid var(--field-border);
    border-radius: 6px;
    background: var(--field);
    color: var(--muted);
    font: inherit;
    cursor: pointer;
  }
  .day[aria-pressed='true'] {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-text);
  }
  code {
    font-family: var(--mono);
    font-size: 11px;
  }
</style>
