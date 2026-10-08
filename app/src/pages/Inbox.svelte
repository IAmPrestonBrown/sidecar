<script lang="ts">
  import { onMount } from 'svelte'
  import EvidenceForm from '../components/EvidenceForm.svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, patch } from '../lib/api'
  import { label, mmss, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Evidence, Hypothesis, Organization, Person } from '../lib/types'

  let items = $state<Evidence[]>([])
  let hyps = $state<Hypothesis[]>([])
  let people = $state<Person[]>([])
  let orgs = $state<Record<string, Organization>>({})
  let index = $state(0)
  let editing = $state(false)
  let error = $state('')

  $effect(() => {
    void app.version
    Promise.all([
      get<Evidence[]>(`${app.base}/c/evidence`),
      get<Hypothesis[]>(`${app.base}/c/hypotheses`),
      get<Person[]>(`${app.base}/c/people`),
      get<Organization[]>(`${app.base}/c/organizations`),
    ])
      .then(([ev, h, p, o]) => {
        items = ev
          .filter((e) => e.review_status === 'proposed')
          .sort((a, b) => (a.at_seconds ?? 0) - (b.at_seconds ?? 0))
        hyps = h.sort((a, b) => a.sort - b.sort)
        people = p
        orgs = Object.fromEntries(o.map((x) => [x.id, x]))
        index = Math.min(index, Math.max(0, items.length - 1))
      })
      .catch((e) => (error = String(e)))
  })

  const current = $derived(items[index])
  const hypById = $derived(Object.fromEntries(hyps.map((h) => [h.id, h])))
  const personById = $derived(Object.fromEntries(people.map((p) => [p.id, p])))

  async function decide(status: 'accepted' | 'rejected', fields: Partial<Evidence> = {}) {
    if (!current) return
    await patch(`${app.base}/c/evidence/${current.id}`, { ...fields, review_status: status })
    editing = false
    app.changed()
  }

  onMount(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName
      if (editing || e.metaKey || e.ctrlKey || e.altKey || ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag))
        return
      const k = e.key.toLowerCase()
      if (k === 'j') index = Math.min(items.length - 1, index + 1)
      else if (k === 'k') index = Math.max(0, index - 1)
      else if (k === 'a') decide('accepted')
      else if (k === 'r') decide('rejected')
      else if (k === 'e') editing = true
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
</script>

<Toolbar title="Inbox" subtitle={`${items.length} evidence items to review`}>
  {#snippet actions()}<span class="muted">J / K move · A accept · E edit · R reject</span>{/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}

{#if items.length === 0}
  <div class="none">
    <p class="strong">Nothing to review.</p>
    <p class="muted">
      Evidence the coach logs during calls lands here. It counts toward a hypothesis only after you accept it.
      Email replies and prospect suggestions will appear here too.
    </p>
  </div>
{:else}
  <div class="split">
    <div class="list">
      {#each items as e, i (e.id)}
        <button
          class="entry"
          class:active={i === index}
          onclick={() => {
            index = i
            editing = false
          }}
        >
          <span class="top"
            ><span class="strong">{label(e.type)}</span><span class="when"
              >{e.at_seconds != null ? mmss(e.at_seconds) : shortDate(e.created_at)}</span
            ></span
          >
          <span class="text">{e.quote ? `“${e.quote}”` : e.note}</span>
        </button>
      {/each}
    </div>

    {#if current}
      <section aria-label="Selected item" class="detail">
        <span class="caption">SUGGESTED EVIDENCE</span>
        {#if editing}
          <EvidenceForm
            initial={current}
            hypotheses={hyps}
            {people}
            submitLabel="Accept"
            onsubmit={(d) => decide('accepted', d)}
            oncancel={() => (editing = false)}
          />
        {:else}
          <blockquote class="selectable">{current.quote ? `“${current.quote}”` : current.note}</blockquote>
          <div class="muted">
            {personById[current.person_id]?.name ?? 'No person'}
            {#if orgs[personById[current.person_id]?.organization_id ?? '']}
              · {orgs[personById[current.person_id]?.organization_id ?? ''].name}{/if}
          </div>
          <dl>
            <dt>Note</dt>
            <dd>{current.note || '—'}</dd>
            <dt>Type</dt>
            <dd>{label(current.type)}</dd>
            <dt>Basis</dt>
            <dd>{label(current.basis)}</dd>
            <dt>Hypotheses</dt>
            <dd>
              {#each current.links as l (l.hypothesis_id)}
                <div>
                  <span class={l.stance}>{label(l.stance)}</span>
                  {hypById[l.hypothesis_id]?.code}
                  {hypById[l.hypothesis_id]?.title}
                </div>
              {:else}None proposed{/each}
            </dd>
          </dl>
          <div class="buttons">
            <button class="btn" onclick={() => decide('rejected')}>Reject</button>
            <button class="btn" onclick={() => (editing = true)}>Edit</button>
            <button class="btn primary" onclick={() => decide('accepted')}>Accept</button>
          </div>
        {/if}
      </section>
    {/if}
  </div>
{/if}

<style>
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
    flex: 1 1 320px;
    max-width: 380px;
    border-right: 1px solid var(--sep);
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .entry {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }
  .entry:hover {
    background: var(--hover);
  }
  .entry.active {
    background: var(--accent);
    color: var(--accent-text);
  }
  .entry .top {
    display: flex;
    gap: 8px;
  }
  .entry .when {
    margin-left: auto;
    opacity: 0.8;
  }
  .entry .text {
    line-height: 1.35;
    opacity: 0.92;
  }
  .detail {
    flex: 999 1 420px;
    min-width: 0;
    max-width: 760px;
    padding: 24px 28px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  blockquote {
    margin: 0;
    font-size: 17px;
    line-height: 1.45;
  }
  dl {
    margin: 0;
    display: grid;
    grid-template-columns: 100px minmax(0, 1fr);
    gap: 8px 12px;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
  }
  .buttons {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }
</style>
