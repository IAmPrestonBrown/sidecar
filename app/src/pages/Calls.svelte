<script lang="ts">
  import { untrack } from 'svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, post } from '../lib/api'
  import { call } from '../lib/call.svelte'
  import { mmss, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Call, Evidence, Organization, Person } from '../lib/types'

  let { personId = '' }: { personId?: string } = $props()

  let calls = $state<Call[]>([])
  let people = $state<Person[]>([])
  let orgs = $state<Record<string, Organization>>({})
  let evidence = $state<Evidence[]>([])
  let starting = $state(false)
  let confirmEnd = $state(false)
  let busy = $state(false)
  let error = $state('')
  let form = $state({ person: '', minutes: 30, notes: '' })

  $effect(() => {
    form.person = personId
    starting = !!personId
  })

  $effect(() => {
    void app.version
    Promise.all([
      get<Call[]>(`${app.base}/c/calls`),
      get<Person[]>(`${app.base}/c/people`),
      get<Organization[]>(`${app.base}/c/organizations`),
      get<Evidence[]>(`${app.base}/c/evidence`),
    ])
      .then(([c, p, o, e]) => {
        calls = c.sort((a, b) => (b.started_at || b.created_at).localeCompare(a.started_at || a.created_at))
        people = p.sort((a, b) => a.name.localeCompare(b.name))
        orgs = Object.fromEntries(o.map((x) => [x.id, x]))
        evidence = e
      })
      .catch((e) => (error = String(e)))
    untrack(() => call.refresh().catch(() => {}))
  })

  const personById = $derived(Object.fromEntries(people.map((p) => [p.id, p])))
  const chosen = $derived(personById[form.person])
  const live = $derived(call.live && call.current?.slug === app.slug ? call.current : null)
  const other = $derived(call.live && call.current?.slug !== app.slug ? call.current : null)
  const finished = $derived(
    call.current && !call.live && call.current.slug === app.slug ? call.current : null,
  )

  function counts(id: string): { proposed: number; accepted: number } {
    const items = evidence.filter((e) => e.call_id === id)
    return {
      proposed: items.filter((e) => e.review_status === 'proposed').length,
      accepted: items.filter((e) => e.review_status === 'accepted').length,
    }
  }

  async function start() {
    error = ''
    busy = true
    try {
      await call.start(form.person, form.minutes, form.notes)
      starting = false
      form.notes = ''
    } catch (e) {
      error = String(e)
    } finally {
      busy = false
    }
  }

  async function end() {
    error = ''
    try {
      await call.end()
    } catch (e) {
      error = String(e)
    } finally {
      confirmEnd = false
    }
  }

  function reveal(id: string) {
    post(`${app.base}/calls/${id}/reveal`).catch((e) => (error = String(e)))
  }
</script>

<Toolbar title="Calls" subtitle={`${calls.length} recorded`}>
  {#snippet actions()}
    <button class="btn primary" disabled={call.live} onclick={() => (starting = true)}>New call</button>
  {/snippet}
</Toolbar>

<div class="body">
  {#if error}<div class="error-banner">{error}</div>{/if}

  {#if live}
    <section class="group live" aria-live="polite">
      <div class="row">
        <span class="dot" class:on={live.state === 'ready'}></span>
        <span class="stack">
          <span class="strong">Call with {live.person_name}</span>
          <span class="muted">
            {#if live.state === 'starting'}Starting the coach and running checks…
            {:else if live.state === 'ready'}Coach open. Press Start in the call window when you have consent.
            {:else}Ending. Saving audio and the final transcript…{/if}
          </span>
        </span>
        <span class="spacer"></span>
        {#if live.state === 'ready'}
          <button class="btn" onclick={() => call.showWindow()}>Show call window</button>
          {#if confirmEnd}
            <button class="btn" onclick={() => (confirmEnd = false)}>Keep going</button>
            <button class="btn danger" onclick={end}>End call</button>
          {:else}
            <button class="btn" onclick={() => (confirmEnd = true)}>End call…</button>
          {/if}
        {/if}
      </div>
      {#if call.quitBlocked}
        <p class="mixed">Sidecar stays open during a call. End the call first, then quit.</p>
      {/if}
    </section>
  {:else if other}
    <section class="group live">
      <div class="row">
        <span class="dot on"></span>
        <span class="muted">A call with {other.person_name} is running in another project.</span>
        <span class="spacer"></span>
        <button class="btn" onclick={() => call.showWindow()}>Show call window</button>
      </div>
    </section>
  {:else if finished}
    <section class="group live">
      {#if finished.state === 'failed'}
        <p class="strong">The call did not start.</p>
        <p class="muted selectable">{finished.error}</p>
        {#if finished.output.length}
          <pre class="selectable">{finished.output.join('\n')}</pre>
        {/if}
      {:else}
        <p>
          <span class="strong">Call with {finished.person_name} saved.</span>
          {#if finished.call_id}
            <span class="muted">Its evidence is waiting in the</span> <a href="#/inbox">Inbox</a>.
          {:else if finished.error}
            <span class="muted selectable">It could not be added to the project: {finished.error}</span>
          {/if}
        </p>
      {/if}
    </section>
  {/if}

  {#if starting && !call.live}
    <form
      class="group pad"
      onsubmit={(e) => {
        e.preventDefault()
        start()
      }}
    >
      <div class="form-grid">
        <label for="c-person">Person</label>
        <select id="c-person" class="select" bind:value={form.person}>
          <option value="" disabled>Choose someone</option>
          {#each people as p (p.id)}
            <option value={p.id}
              >{p.name}{orgs[p.organization_id] ? `, ${orgs[p.organization_id].name}` : ''}</option
            >
          {/each}
        </select>
        <label for="c-min">Planned minutes</label>
        <input
          id="c-min"
          class="field"
          type="number"
          min="5"
          max="180"
          style="width: 80px"
          bind:value={form.minutes}
        />
        <label for="c-notes">Notes for the coach</label>
        <textarea
          id="c-notes"
          class="field"
          rows="3"
          placeholder="Anything the coach should know about this person"
          bind:value={form.notes}></textarea>
        <span></span>
        <p class="muted">
          The coach records through this Mac's microphone with the phone on speaker. It checks the microphone
          and both API keys first, and recording starts only when you press Start in the call window.
          {#if chosen?.do_not_contact}<span class="mixed">This person is marked do not contact.</span>{/if}
        </p>
        <span></span>
        <span class="inline">
          <button type="button" class="btn" onclick={() => (starting = false)}>Cancel</button>
          <button type="submit" class="btn primary" disabled={!form.person || busy}>Open coach</button>
        </span>
      </div>
    </form>
  {/if}

  <div class="scroll">
    <table class="list">
      <thead>
        <tr>
          <th style="width: 90px">Date</th>
          <th>Person</th>
          <th style="width: 80px">Length</th>
          <th style="width: 64px">Marks</th>
          <th style="width: 150px">Evidence</th>
          <th style="width: 120px"></th>
        </tr>
      </thead>
      <tbody>
        {#each calls as c (c.id)}
          {@const n = counts(c.id)}
          {@const p = personById[c.person_id]}
          <tr>
            <td class="muted">{shortDate(c.started_at || c.created_at)}</td>
            <td>
              {#if p}<a href={`#/person/${p.id}`} class="strong">{p.name}</a>{:else}<span>{c.title}</span
                >{/if}
              {#if p && orgs[p.organization_id]}<br /><span class="muted">{orgs[p.organization_id].name}</span
                >{/if}
            </td>
            <td class="num">{c.duration_s ? mmss(c.duration_s) : ''}</td>
            <td class="num">{c.marks || ''}</td>
            <td>
              {n.accepted} accepted{#if n.proposed}, <a href="#/inbox">{n.proposed} to review</a>{/if}
            </td>
            <td><button class="link-btn" onclick={() => reveal(c.id)}>Show in Finder</button></td>
          </tr>
        {:else}
          <tr><td colspan="6" class="muted">No calls yet.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

<style>
  .body {
    padding: 16px 24px 32px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .live,
  .pad {
    padding: 14px;
    max-width: 860px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .spacer {
    flex: 1 1 auto;
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--faint);
    flex: none;
  }
  .dot.on {
    background: var(--contradicts);
  }
  .inline {
    display: flex;
    gap: 8px;
  }
  pre {
    font-family: var(--mono);
    font-size: 11px;
    max-height: 200px;
    overflow: auto;
    white-space: pre-wrap;
  }
  .scroll {
    overflow-x: auto;
  }
  table {
    min-width: 640px;
  }
</style>
