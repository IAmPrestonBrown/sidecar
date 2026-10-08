<script lang="ts">
  import Toolbar from '../components/Toolbar.svelte'
  import { get, patch, post } from '../lib/api'
  import { app } from '../lib/state.svelte'
  import { autosize } from '../lib/autosize'
  import type { EmailSettings, ProjectMeta } from '../lib/types'

  let meta = $state<ProjectMeta | null>(null)
  let exported = $state('')
  let error = $state('')

  const TEMPLATES: [keyof EmailSettings, string, number][] = [
    ['body_template', 'First email', 10],
    ['follow_up_template', 'Follow-up', 5],
    ['final_template', 'Final note', 5],
  ]

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
    } catch (e) {
      error = String(e)
    }
  }

  function num(e: Event): number {
    return Number((e.currentTarget as HTMLInputElement).value)
  }

  function text(e: Event): string {
    return (e.currentTarget as HTMLInputElement).value
  }

  async function exportProject() {
    const out = await post<{ json: string; markdown: string }>(`${app.base}/export`)
    exported = `${out.json}\n${out.markdown}`
  }
</script>

<Toolbar title="Settings" subtitle={meta?.name ?? ''} />

<div class="body">
  {#if error}<div class="error-banner">{error}</div>{/if}
  {#if meta}
    <section>
      <h2>Project data</h2>
      <div class="group pad">
        <div class="form-grid">
          <label for="pname">Name</label>
          <input id="pname" class="field" value={meta.name} onblur={(e) => save({ name: text(e) })} />
          <span class="label">Folder</span>
          <span class="inline"
            ><span class="selectable path">{meta.path}</span>
            <button class="btn small" onclick={() => post(`${app.base}/reveal`)}>Show in Finder</button></span
          >
          <span class="label">Export</span>
          <span class="inline">
            <button class="btn small" onclick={exportProject}>Export JSON and Markdown</button>
            <span class="muted">One file each, for ChatGPT or other tools.</span>
          </span>
          {#if exported}<span></span>
            <pre class="selectable">{exported}</pre>{/if}
        </div>
      </div>
    </section>

    <section>
      <h2>Templates</h2>
      <div class="group pad">
        <div class="form-grid">
          <label for="t-subject">Subject</label>
          <input
            id="t-subject"
            class="field"
            value={meta.email.subject_template}
            onblur={(e) => save({ email: { subject_template: text(e) } })}
          />
          {#each TEMPLATES as [key, name, rows] (key)}
            <label for={`t-${key}`}>{name}</label>
            <textarea
              id={`t-${key}`}
              class="field template"
              {rows}
              value={String(meta.email[key])}
              use:autosize={String(meta.email[key])}
              onblur={(e) => save({ email: { [key]: text(e) } })}></textarea>
          {/each}
          <span></span>
          <p class="muted">
            <code>{'{first_name}'}</code>, <code>{'{organization}'}</code> and
            <code>{'{optional_sentence}'}</code> are filled in for each person. An empty optional sentence removes
            its line. Changes apply to new drafts only.
          </p>
        </div>
      </div>
    </section>

    <section>
      <h2>Sending</h2>
      <div class="group pad">
        <div class="form-grid">
          <label for="cap">Daily cap</label>
          <span class="inline"
            ><input
              id="cap"
              class="field"
              style="width: 70px"
              type="number"
              min="1"
              max="200"
              value={meta.sending.daily_cap}
              onchange={(e) => save({ sending: { daily_cap: num(e) } })}
            />
            <span class="muted">emails per day across the project</span></span
          >
          <span class="label">Window</span>
          <span class="inline">
            <input
              class="field"
              type="time"
              aria-label="Window start"
              value={meta.sending.window_start}
              onchange={(e) => save({ sending: { window_start: text(e) } })}
            />
            <span class="muted">to</span>
            <input
              class="field"
              type="time"
              aria-label="Window end"
              value={meta.sending.window_end}
              onchange={(e) => save({ sending: { window_end: text(e) } })}
            />
            <span class="muted">in the recipient's time zone when known</span>
          </span>
          <span class="label">Spacing</span>
          <span class="inline">
            <input
              class="field"
              style="width: 60px"
              type="number"
              min="1"
              aria-label="Minimum minutes between sends"
              value={meta.sending.min_gap_minutes}
              onchange={(e) => save({ sending: { min_gap_minutes: num(e) } })}
            />
            <span class="muted">to</span>
            <input
              class="field"
              style="width: 60px"
              type="number"
              min="1"
              aria-label="Maximum minutes between sends"
              value={meta.sending.max_gap_minutes}
              onchange={(e) => save({ sending: { max_gap_minutes: num(e) } })}
            />
            <span class="muted">minutes apart, random</span>
          </span>
        </div>
      </div>
    </section>

    <section>
      <h2>Email</h2>
      <div class="group pad">
        <div class="form-grid">
          <label for="sender">Sender name</label>
          <input
            id="sender"
            class="field"
            style="width: 220px"
            value={meta.email.sender_name}
            onblur={(e) => save({ email: { sender_name: text(e) } })}
          />
          <span class="label">Footer</span>
          <label class="check"
            ><input
              type="checkbox"
              checked={meta.email.footer_enabled}
              onchange={(e) =>
                save({ email: { footer_enabled: (e.currentTarget as HTMLInputElement).checked } })}
            />
            Add a postal address and opt-out line</label
          >
          <span></span>
          <p class="muted">
            Off for research requests. Turn it on if outreach ever promotes a product or service.
          </p>
          {#if meta.email.footer_enabled}
            <label for="addr">Postal address</label>
            <input
              id="addr"
              class="field"
              value={meta.email.postal_address}
              onblur={(e) => save({ email: { postal_address: text(e) } })}
            />
            <label for="opt">Opt-out line</label>
            <input
              id="opt"
              class="field"
              value={meta.email.opt_out_line}
              onblur={(e) => save({ email: { opt_out_line: text(e) } })}
            />
          {/if}
          <span class="label">Gmail</span>
          <span class="muted">Not connected. Gmail support is not available yet.</span>
        </div>
      </div>
    </section>
  {/if}
</div>

<style>
  .body {
    padding: 20px 24px 40px;
    max-width: 760px;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  h2 {
    margin: 0 12px;
    font-size: 13px;
    font-weight: 600;
  }
  .template {
    font-size: 13px;
    line-height: 1.5;
    overflow: hidden;
  }
  code {
    font-family: var(--mono);
    font-size: 12px;
  }
  .pad {
    padding: 14px;
  }
  .inline {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .check {
    display: flex;
    gap: 6px;
    align-items: center;
    color: var(--text) !important;
  }
  .path {
    overflow-wrap: anywhere;
  }
  pre {
    margin: 0;
    font-family: var(--mono);
    font-size: 11px;
    white-space: pre-wrap;
    color: var(--muted);
  }
</style>
