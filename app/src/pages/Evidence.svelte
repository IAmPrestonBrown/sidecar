<script lang="ts">
  import EvidenceForm from '../components/EvidenceForm.svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { del, get, patch } from '../lib/api'
  import { EVIDENCE_TYPES, STANCES, isStrong, label, mmss, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Evidence, Hypothesis, Organization, Person } from '../lib/types'

  let evidence = $state<Evidence[]>([])
  let hyps = $state<Hypothesis[]>([])
  let people = $state<Person[]>([])
  let orgs = $state<Record<string, Organization>>({})
  let fHyp = $state('')
  let fStance = $state('')
  let fType = $state('')
  let q = $state('')
  let selected = $state('')
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
        evidence = ev
          .filter((e) => e.review_status === 'accepted')
          .sort((a, b) => b.created_at.localeCompare(a.created_at))
        hyps = h.sort((a, b) => a.sort - b.sort)
        people = p
        orgs = Object.fromEntries(o.map((x) => [x.id, x]))
      })
      .catch((e) => (error = String(e)))
  })

  const hypById = $derived(Object.fromEntries(hyps.map((h) => [h.id, h])))
  const personById = $derived(Object.fromEntries(people.map((p) => [p.id, p])))

  const rows = $derived(
    evidence.filter((e) => {
      if (fHyp && !e.links.some((l) => l.hypothesis_id === fHyp)) return false
      if (fStance && !e.links.some((l) => l.stance === fStance && (!fHyp || l.hypothesis_id === fHyp)))
        return false
      if (fType === 'strong' && !isStrong(e.type, e.basis)) return false
      if (fType && fType !== 'strong' && e.type !== fType) return false
      if (q && !`${e.quote} ${e.note}`.toLowerCase().includes(q.toLowerCase())) return false
      return true
    }),
  )
  const current = $derived(evidence.find((e) => e.id === selected))

  function orgName(e: Evidence): string {
    return orgs[e.organization_id || personById[e.person_id]?.organization_id || '']?.name ?? ''
  }

  async function saveEdit(draft: Partial<Evidence>) {
    if (!current) return
    await patch(`${app.base}/c/evidence/${current.id}`, draft)
    editing = false
    app.changed()
  }

  async function remove() {
    if (!current) return
    await del(`${app.base}/c/evidence/${current.id}`)
    selected = ''
    app.changed()
  }
</script>

<Toolbar title="Evidence" subtitle={`${rows.length} accepted items`}>
  {#snippet actions()}
    <label class="sr-only" for="f-h">Hypothesis</label>
    <select id="f-h" class="select" bind:value={fHyp}>
      <option value="">All hypotheses</option>
      {#each hyps as h (h.id)}<option value={h.id}>{h.code} {h.title}</option>{/each}
    </select>
    <label class="sr-only" for="f-s">Stance</label>
    <select id="f-s" class="select" bind:value={fStance}>
      <option value="">Any stance</option>
      {#each STANCES as [v, l] (v)}<option value={v}>{l}</option>{/each}
    </select>
    <label class="sr-only" for="f-t">Type</label>
    <select id="f-t" class="select" bind:value={fType}>
      <option value="">Any type</option>
      <option value="strong">Strong only</option>
      {#each EVIDENCE_TYPES as [v, l] (v)}<option value={v}>{l}</option>{/each}
    </select>
    <label class="sr-only" for="f-q">Search evidence</label>
    <input id="f-q" type="search" class="field search" placeholder="Search quotes" bind:value={q} />
  {/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}

<div class="split">
  <div class="table">
    {#if rows.length}
      <table class="list">
        <thead>
          <tr>
            <th style="width: 64px">Date</th>
            <th>Quote</th>
            <th style="width: 170px">Person</th>
            <th style="width: 110px">Type</th>
            <th style="width: 150px">Hypotheses</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as e (e.id)}
            <tr
              class="clickable"
              class:selected={selected === e.id}
              onclick={() => {
                selected = e.id
                editing = false
              }}
            >
              <td class="muted">{shortDate(e.created_at)}</td>
              <td>{e.quote ? `“${e.quote}”` : e.note}</td>
              <td>{personById[e.person_id]?.name ?? ''}<br /><span class="muted">{orgName(e)}</span></td>
              <td>{label(e.type)}</td>
              <td>
                {#each e.links as l (l.hypothesis_id)}
                  <div class={l.stance}>{label(l.stance)} {hypById[l.hypothesis_id]?.code ?? '?'}</div>
                {/each}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <p class="empty">
        No accepted evidence{fHyp || fStance || fType || q
          ? ' matches these filters'
          : ' yet. Evidence from calls appears in the Inbox for review first'}.
      </p>
    {/if}
  </div>

  <aside aria-label="Inspector">
    {#if current && editing}
      <EvidenceForm
        initial={current}
        hypotheses={hyps}
        {people}
        onsubmit={saveEdit}
        oncancel={() => (editing = false)}
      />
    {:else if current}
      <div class="caption">SELECTED</div>
      <p class="quote selectable">{current.quote ? `“${current.quote}”` : current.note}</p>
      <dl>
        <dt>Note</dt>
        <dd>{current.note || '—'}</dd>
        <dt>Person</dt>
        <dd>{personById[current.person_id]?.name ?? '—'}</dd>
        <dt>Org</dt>
        <dd>{orgName(current) || '—'}</dd>
        <dt>Type</dt>
        <dd>{label(current.type)} · {isStrong(current.type, current.basis) ? 'strong' : 'weak'}</dd>
        <dt>Basis</dt>
        <dd>{label(current.basis)}</dd>
        <dt>Links</dt>
        <dd>
          {#each current.links as l (l.hypothesis_id)}<div class={l.stance}>
              {label(l.stance)}
              {hypById[l.hypothesis_id]?.code}
            </div>{/each}
        </dd>
        <dt>Source</dt>
        <dd>{label(current.source)}{current.at_seconds != null ? ` at ${mmss(current.at_seconds)}` : ''}</dd>
      </dl>
      <div class="buttons">
        <button class="btn small" onclick={() => (editing = true)}>Edit</button>
        <button class="btn small danger" onclick={remove}>Remove</button>
      </div>
    {:else}
      <p class="muted">Select an item to see and edit it.</p>
    {/if}
  </aside>
</div>

<style>
  .split {
    display: flex;
    flex-wrap: wrap;
    flex: 1 1 auto;
    min-height: 0;
  }
  .table {
    flex: 999 1 560px;
    min-width: 0;
    overflow-x: auto;
    padding: 8px 16px 24px;
  }
  table {
    min-width: 720px;
  }
  aside {
    flex: 1 1 300px;
    max-width: 380px;
    border-left: 1px solid var(--sep);
    background: var(--panel);
    padding: 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .quote {
    font-size: 14px;
    line-height: 1.45;
  }
  dl {
    margin: 0;
    display: grid;
    grid-template-columns: 70px minmax(0, 1fr);
    gap: 8px 10px;
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
  }
  .empty {
    padding: 24px 8px;
  }
</style>
