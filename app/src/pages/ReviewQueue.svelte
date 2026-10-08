<script lang="ts">
  import { onMount } from 'svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, patch, post } from '../lib/api'
  import { autosize } from '../lib/autosize'
  import { app } from '../lib/state.svelte'
  import type { QueueItem, SendingStatus } from '../lib/types'

  interface ApproveResult {
    approved: string[]
    refused: Record<string, string>
  }

  let items = $state<QueueItem[]>([])
  let selectedId = $state('')
  let checked = $state<string[]>([])
  let subject = $state('')
  let body = $state('')
  let confirmAddress = $state(false)
  let pendingBulk = $state<string[] | null>(null)
  let bulkConfirmAddress = $state(false)
  let notice = $state('')
  let error = $state('')

  let sending = $state<SendingStatus | null>(null)

  async function load() {
    ;[items, sending] = await Promise.all([
      get<QueueItem[]>(`${app.base}/outreach/queue`),
      get<SendingStatus>(`${app.base}/sending`),
    ])
    if (!items.some((i) => i.id === selectedId)) selectedId = drafts[0]?.id ?? items[0]?.id ?? ''
    checked = checked.filter((id) => items.some((i) => i.id === id && i.status === 'draft'))
  }

  $effect(() => {
    void app.version
    load().catch((e) => (error = String(e)))
  })

  const drafts = $derived(items.filter((i) => i.status === 'draft'))
  const approved = $derived(items.filter((i) => i.status === 'approved'))
  const failed = $derived(items.filter((i) => i.status === 'failed'))

  async function retry(id: string) {
    await patch(`${app.base}/c/messages/${id}`, { status: 'approved', error: '' })
    app.changed()
  }

  async function draftFollowUps() {
    error = ''
    try {
      const res = await post<{ created: string[] }>(`${app.base}/outreach/follow-ups`)
      notice = res.created.length
        ? `Drafted ${res.created.length} ${res.created.length === 1 ? 'follow-up' : 'follow-ups'}.`
        : 'No follow-ups are due.'
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }
  const current = $derived(items.find((i) => i.id === selectedId))
  const passing = $derived(drafts.filter((d) => !d.checks.some((c) => c.level === 'fail')))
  const unverified = (item: QueueItem) =>
    item.checks.some((c) => c.name === 'Email address' && c.level === 'warn')
  const fails = (item: QueueItem) => item.checks.filter((c) => c.level === 'fail').length

  $effect(() => {
    subject = current?.subject ?? ''
    body = current?.body ?? ''
    confirmAddress = false
  })

  const dirty = $derived(!!current && (subject !== current.subject || body !== current.body))

  async function save() {
    if (!current || !dirty) return
    await patch(`${app.base}/c/messages/${current.id}`, { subject, body })
    app.changed()
  }

  async function approve(ids: string[], confirm: boolean) {
    error = ''
    await save()
    const res = await post<ApproveResult>(`${app.base}/outreach/approve`, {
      ids,
      confirm_inferred: confirm,
    })
    const refused = Object.values(res.refused)
    notice =
      `Approved ${res.approved.length}.` +
      (refused.length ? ` Not approved: ${refused.length} (${[...new Set(refused)].join('; ')}).` : '')
    pendingBulk = null
    bulkConfirmAddress = false
    app.changed()
  }

  async function skipIds(ids: string[]) {
    await post(`${app.base}/outreach/skip`, { ids })
    app.changed()
  }

  function toggle(id: string) {
    checked = checked.includes(id) ? checked.filter((x) => x !== id) : [...checked, id]
  }

  function move(step: number) {
    const list = [...drafts, ...approved]
    const i = list.findIndex((x) => x.id === selectedId)
    const next = list[Math.min(list.length - 1, Math.max(0, i + step))]
    if (next) selectedId = next.id
  }

  onMount(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName
      if (e.metaKey || e.ctrlKey || e.altKey || ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return
      const k = e.key.toLowerCase()
      if (k === 'j') move(1)
      else if (k === 'k') move(-1)
      else if (k === 'a' && current?.status === 'draft' && !unverified(current) && !fails(current))
        approve([current.id], false)
      else if (k === 's' && current) skipIds([current.id])
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      save()
    }
  })
</script>

<Toolbar title="Review queue" subtitle={`${drafts.length} drafts · ${approved.length} approved`}>
  {#snippet actions()}
    <button class="btn" onclick={draftFollowUps}>Draft due follow-ups</button>
    {#if checked.length}
      <button class="btn" onclick={() => (pendingBulk = [...checked])}
        >Approve {checked.length} selected…</button
      >
    {/if}
    <button class="btn" disabled={!passing.length} onclick={() => (pendingBulk = passing.map((d) => d.id))}>
      Approve all passing ({passing.length})…
    </button>
  {/snippet}
</Toolbar>

<div class="banner muted">
  {#if !sending || !sending.connected}
    Approved emails wait here. Nothing is sent until you connect Gmail in <a href="#/settings">Settings</a>.
  {:else if !sending.active}
    Sending is off for this project. Approved emails wait here until you turn it on in
    <a href="#/settings">Settings</a>.
  {:else}
    Sending is on: {sending.sent_today} of {sending.daily_cap} sent today, {sending.waiting} waiting.
    {sending.blocked ? `${sending.blocked}.` : 'Sends go out one at a time inside the send window.'}
  {/if}
  {#if sending?.last_error}<span class="contradicts">Last error: {sending.last_error}</span>{/if}
</div>

{#if pendingBulk}
  <div class="confirm">
    <span class="strong">Approve {pendingBulk.length} {pendingBulk.length === 1 ? 'email' : 'emails'}?</span>
    <span class="muted">Drafts with failed checks are left as drafts.</span>
    <label class="check"
      ><input type="checkbox" bind:checked={bulkConfirmAddress} /> I checked the unverified addresses</label
    >
    <span class="spacer"></span>
    <button class="btn" onclick={() => (pendingBulk = null)}>Cancel</button>
    <button class="btn primary" onclick={() => pendingBulk && approve(pendingBulk, bulkConfirmAddress)}
      >Approve</button
    >
  </div>
{/if}
{#if notice}<div class="notice">{notice}</div>{/if}
{#if error}<div class="error-banner" style="margin: 0 24px">{error}</div>{/if}

{#if items.length === 0}
  <div class="none">
    <p class="strong">No drafts.</p>
    <p class="muted">
      Select people on the People page and choose Draft emails, or use Draft email on a person. Drafts use the
      template from your outreach brief, which you can edit in Settings.
    </p>
  </div>
{:else}
  <div class="split">
    <nav class="list" aria-label="Drafts">
      {#each [{ title: 'Drafts', rows: drafts }, { title: 'Approved, waiting to send', rows: approved }, { title: 'Not sent', rows: failed }] as group (group.title)}
        {#if group.rows.length}
          <div class="caption group-title">{group.title}</div>
          {#each group.rows as item (item.id)}
            <div class="entry" class:active={item.id === selectedId}>
              {#if item.status === 'draft'}
                <input
                  type="checkbox"
                  aria-label={`Select ${item.person?.name ?? 'draft'}`}
                  checked={checked.includes(item.id)}
                  onchange={() => toggle(item.id)}
                />
              {/if}
              <button class="pick" onclick={() => (selectedId = item.id)}>
                <span class="top">
                  <span class="strong">{item.person?.name ?? 'Unknown person'}</span>
                  {#if fails(item)}<span class="flag fail">{fails(item)} failed</span>
                  {:else if unverified(item)}<span class="flag warn">Unverified</span>{/if}
                </span>
                <span class="sub">{item.organization?.name ?? ''}</span>
              </button>
            </div>
          {/each}
        {/if}
      {/each}
    </nav>

    {#if current}
      <section class="draft" aria-label="Email">
        <div class="head">
          <span class="muted">To</span>
          <span class="selectable"
            >{current.person?.name} &lt;{current.person?.email || 'no address'}&gt;</span
          >
          <label for="subj" class="muted">Subject</label>
          <input
            id="subj"
            class="field"
            bind:value={subject}
            onblur={save}
            disabled={current.status !== 'draft'}
          />
        </div>
        <label class="sr-only" for="body">Email body</label>
        <textarea
          id="body"
          class="field body"
          bind:value={body}
          use:autosize={body}
          onblur={save}
          disabled={current.status !== 'draft'}></textarea>
        <div class="actions">
          <button class="btn" onclick={() => skipIds([current.id])}>Skip <span class="faint">S</span></button>
          <span class="spacer"></span>
          {#if current.status === 'draft'}
            {#if unverified(current)}
              <label class="check"
                ><input type="checkbox" bind:checked={confirmAddress} /> I checked this address</label
              >
            {/if}
            <button
              class="btn primary"
              disabled={!!fails(current) || (unverified(current) && !confirmAddress)}
              onclick={() => approve([current.id], confirmAddress)}
            >
              Approve <span class="key">A</span>
            </button>
          {:else if current.status === 'failed'}
            <span class="contradicts">{current.error || 'Sending failed.'}</span>
            <button class="btn" onclick={() => retry(current.id)}>Try again</button>
          {:else}
            <span class="muted">Approved. Waiting to send.</span>
          {/if}
        </div>
      </section>

      <aside aria-label="Checks">
        <section>
          <h2>{current.person?.name}</h2>
          <span class="muted"
            >{current.person?.role}{current.person?.role ? ' · ' : ''}{current.organization?.name ?? ''}</span
          >
          <span class="muted">Segment: {current.person?.segment || 'Not known'}</span>
          {#if current.person}<a href={`#/person/${current.person.id}`}>Open person</a>{/if}
        </section>
        <section>
          <h2>Checks</h2>
          <ul>
            {#each current.checks as c (c.name)}
              <li>
                <span class={`mark ${c.level}`}
                  >{c.level === 'pass' ? 'Pass' : c.level === 'warn' ? 'Note' : 'Fail'}</span
                >
                <span class="stack"
                  ><span>{c.name}</span>{#if c.detail}<span class="muted">{c.detail}</span>{/if}</span
                >
              </li>
            {/each}
          </ul>
          {#if dirty}<p class="muted">Checks update when you leave the editor.</p>{/if}
        </section>
        {#if current.person?.sources?.length}
          <section>
            <h2>Sources</h2>
            {#each current.person.sources as src, i (i)}
              <span class="selectable muted">{src.title || src.url}{src.quote ? `: “${src.quote}”` : ''}</span
              >
            {/each}
          </section>
        {/if}
      </aside>
    {/if}
  </div>
{/if}

<style>
  .banner {
    padding: 8px 24px;
    border-bottom: 1px solid var(--sep);
    background: var(--panel);
  }
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    margin: 12px 24px 0;
    padding: 10px 14px;
    border: 1px solid var(--sep);
    border-radius: 8px;
    background: var(--panel);
  }
  .notice {
    margin: 12px 24px 0;
    padding: 8px 12px;
    border-radius: 8px;
    background: var(--accent-tint);
  }
  .spacer {
    flex: 1 1 auto;
  }
  .check {
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }
  .none {
    padding: 32px 24px;
    max-width: 560px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .split {
    display: flex;
    flex-wrap: wrap;
    flex: 1 1 auto;
    min-height: 0;
  }
  .list {
    flex: 1 1 260px;
    max-width: 300px;
    border-right: 1px solid var(--sep);
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .group-title {
    padding: 8px 8px 4px;
  }
  .entry {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 4px 6px;
    border-radius: 8px;
  }
  .entry.active {
    background: var(--accent);
    color: var(--accent-text);
  }
  .entry input {
    margin-top: 8px;
  }
  .pick {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 4px 2px;
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
    color: inherit;
  }
  .top {
    display: flex;
    gap: 6px;
  }
  .sub {
    opacity: 0.8;
  }
  .flag {
    margin-left: auto;
    font-size: 12px;
  }
  .flag.fail {
    color: var(--contradicts);
  }
  .flag.warn {
    color: var(--mixed);
  }
  .entry.active .flag {
    color: inherit;
  }
  .draft {
    flex: 999 1 420px;
    min-width: 0;
    max-width: 720px;
    padding: 16px 24px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .head {
    display: grid;
    grid-template-columns: 64px minmax(0, 1fr);
    gap: 8px 10px;
    align-items: center;
  }
  .body {
    min-height: 220px;
    font-size: 14px;
    line-height: 1.55;
    overflow: hidden;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }
  .key {
    opacity: 0.75;
  }
  aside {
    flex: 1 1 260px;
    max-width: 320px;
    border-left: 1px solid var(--sep);
    background: var(--panel);
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  aside section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  h2 {
    font-size: 13px;
    font-weight: 600;
  }
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  li {
    display: flex;
    gap: 8px;
    align-items: baseline;
  }
  .mark {
    width: 36px;
    font-weight: 600;
    flex: none;
  }
  .mark.pass {
    color: var(--supports);
  }
  .mark.warn {
    color: var(--mixed);
  }
  .mark.fail {
    color: var(--contradicts);
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
