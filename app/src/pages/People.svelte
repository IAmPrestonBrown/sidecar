<script lang="ts">
  import CsvImport from '../components/CsvImport.svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, post } from '../lib/api'
  import { EMAIL_CONFIDENCE, STAGES, label, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Organization, Person } from '../lib/types'

  let people = $state<Person[]>([])
  let orgs = $state<Organization[]>([])
  let view = $state<'table' | 'board'>('table')
  let fStage = $state('')
  let fSegment = $state('')
  let q = $state('')
  let adding = $state(false)
  let importing = $state(false)
  let selected = $state<string[]>([])
  let notice = $state('')
  let draft = $state({
    name: '',
    org: '',
    role: '',
    email: '',
    email_confidence: 'inferred_direct',
    segment: '',
  })
  let error = $state('')

  $effect(() => {
    void app.version
    Promise.all([get<Person[]>(`${app.base}/c/people`), get<Organization[]>(`${app.base}/c/organizations`)])
      .then(([p, o]) => {
        people = p.sort((a, b) => a.name.localeCompare(b.name))
        orgs = o.sort((a, b) => a.name.localeCompare(b.name))
      })
      .catch((e) => (error = String(e)))
  })

  const orgById = $derived(Object.fromEntries(orgs.map((o) => [o.id, o])))
  const rows = $derived(
    people.filter((p) => {
      if (fStage && p.stage !== fStage) return false
      if (fSegment && p.segment !== fSegment) return false
      const hay = `${p.name} ${orgById[p.organization_id]?.name ?? ''} ${p.role}`.toLowerCase()
      return !q || hay.includes(q.toLowerCase())
    }),
  )
  const columns = $derived(
    STAGES.map(([v, l]) => ({ v, l, items: rows.filter((p) => p.stage === v) })).filter(
      (c) => c.items.length,
    ),
  )

  const matchedOrg = $derived(
    orgs.find((o) => [o.name, ...o.aliases].some((n) => n.toLowerCase() === draft.org.trim().toLowerCase())),
  )
  const coworkers = $derived(matchedOrg ? people.filter((p) => p.organization_id === matchedOrg.id) : [])

  const allSelected = $derived(rows.length > 0 && rows.every((p) => selected.includes(p.id)))

  function toggle(id: string) {
    selected = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]
  }

  function toggleAll() {
    selected = allSelected ? [] : rows.map((p) => p.id)
  }

  async function draftEmails() {
    error = ''
    try {
      const res = await post<{ created: string[]; errors: Record<string, string> }>(
        `${app.base}/outreach/drafts`,
        { person_ids: selected },
      )
      const failed = Object.keys(res.errors).length
      notice = `Drafted ${res.created.length} ${res.created.length === 1 ? 'email' : 'emails'}.${failed ? ` ${failed} could not be drafted.` : ''}`
      selected = []
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }

  async function addPerson() {
    error = ''
    try {
      let orgId = matchedOrg?.id ?? ''
      if (!orgId && draft.org.trim()) {
        orgId = (await post<Organization>(`${app.base}/c/organizations`, { name: draft.org.trim() })).id
      }
      const person = await post<Person>(`${app.base}/c/people`, {
        name: draft.name.trim(),
        first_name: draft.name.trim().split(/\s+/)[0],
        organization_id: orgId,
        role: draft.role,
        email: draft.email.trim(),
        email_confidence: draft.email.trim() ? draft.email_confidence : 'unavailable',
        segment: draft.segment,
        researched_on: new Date().toISOString().slice(0, 10),
      })
      adding = false
      app.changed()
      app.go('person', person.id)
    } catch (e) {
      error = String(e)
    }
  }
</script>

<Toolbar title="People" subtitle={`${rows.length} of ${people.length}`}>
  {#snippet actions()}
    <div class="segmented" role="tablist" aria-label="View">
      <button role="tab" aria-selected={view === 'table'} onclick={() => (view = 'table')}>Table</button>
      <button role="tab" aria-selected={view === 'board'} onclick={() => (view = 'board')}>Board</button>
    </div>
    <label class="sr-only" for="f-stage">Stage</label>
    <select id="f-stage" class="select" bind:value={fStage}>
      <option value="">All stages</option>
      {#each STAGES as [v, l] (v)}<option value={v}>{l}</option>{/each}
    </select>
    <label class="sr-only" for="f-seg">Segment</label>
    <select id="f-seg" class="select" bind:value={fSegment}>
      <option value="">All segments</option>
      {#each app.segments as s (s)}<option value={s}>{s}</option>{/each}
    </select>
    <label class="sr-only" for="f-q">Search people</label>
    <input id="f-q" type="search" class="field search" placeholder="Search" bind:value={q} />
    {#if selected.length}
      <button class="btn" onclick={draftEmails}
        >Draft {selected.length} {selected.length === 1 ? 'email' : 'emails'}</button
      >
    {/if}
    <button class="btn" onclick={() => (importing = true)}>Import CSV…</button>
    <button class="btn primary" onclick={() => (adding = true)}>Add person</button>
  {/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}
{#if notice}
  <div class="notice">{notice} <a href="#/queue">Open the review queue</a></div>
{/if}
{#if importing}<CsvImport onclose={() => (importing = false)} />{/if}

{#if adding}
  <form
    class="group add"
    onsubmit={(e) => {
      e.preventDefault()
      addPerson()
    }}
  >
    <div class="form-grid" style="padding: 14px">
      <label for="p-name">Name</label>
      <input id="p-name" class="field" bind:value={draft.name} />
      <label for="p-org">Organization</label>
      <input id="p-org" class="field" list="org-names" bind:value={draft.org} />
      <datalist id="org-names"
        >{#each orgs as o (o.id)}<option value={o.name}></option>{/each}</datalist
      >
      {#if matchedOrg?.already_contacted || coworkers.length}
        <span></span>
        <p class="mixed">
          {matchedOrg?.already_contacted ? `${matchedOrg.name} was already contacted. ` : ''}
          {coworkers.length
            ? `Already listed here: ${coworkers.map((c) => c.name).join(', ')}. One contact per organization per wave.`
            : ''}
        </p>
      {/if}
      <label for="p-role">Role</label>
      <input id="p-role" class="field" bind:value={draft.role} />
      <label for="p-email">Email</label>
      <span class="inline">
        <input id="p-email" class="field" bind:value={draft.email} />
        <label class="sr-only" for="p-conf">Email confidence</label>
        <select id="p-conf" class="select" bind:value={draft.email_confidence}>
          {#each EMAIL_CONFIDENCE as [v, l] (v)}<option value={v}>{l}</option>{/each}
        </select>
      </span>
      <label for="p-seg">Segment</label>
      <select id="p-seg" class="select" style="width: 260px" bind:value={draft.segment}>
        <option value="">Not known</option>
        {#each app.segments as s (s)}<option value={s}>{s}</option>{/each}
      </select>
      <span></span>
      <span class="inline">
        <button type="button" class="btn" onclick={() => (adding = false)}>Cancel</button>
        <button type="submit" class="btn primary" disabled={!draft.name.trim()}>Add</button>
      </span>
    </div>
  </form>
{/if}

{#if view === 'table'}
  <div class="scroll">
    <table class="list">
      <thead>
        <tr>
          <th style="width: 32px"
            ><input type="checkbox" aria-label="Select all" checked={allSelected} onchange={toggleAll} /></th
          >
          <th>Name</th>
          <th>Organization</th>
          <th style="width: 170px">Segment</th>
          <th style="width: 120px">Email</th>
          <th style="width: 130px">Stage</th>
          <th>Next action</th>
          <th style="width: 80px">Updated</th>
        </tr>
      </thead>
      <tbody>
        {#each rows as p (p.id)}
          <tr class="clickable" onclick={() => app.go('person', p.id)}>
            <td
              ><input
                type="checkbox"
                aria-label={`Select ${p.name}`}
                checked={selected.includes(p.id)}
                onclick={(e) => e.stopPropagation()}
                onchange={() => toggle(p.id)}
              /></td
            >
            <td
              ><a href={`#/person/${p.id}`} class="strong">{p.name}</a>{#if p.role}<br /><span class="muted"
                  >{p.role}</span
                >{/if}</td
            >
            <td>{orgById[p.organization_id]?.name ?? ''}</td>
            <td>{p.segment}</td>
            <td class={p.email_confidence === 'inferred_direct' ? 'mixed' : ''}
              >{label(p.email_confidence)}</td
            >
            <td class:strong={['interested', 'scheduling', 'confirmed'].includes(p.stage)}
              >{label(p.stage)}</td
            >
            <td>{p.next_action}</td>
            <td class="muted">{shortDate(p.updated_at)}</td>
          </tr>
        {:else}
          <tr><td colspan="8" class="muted">No people match.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
{:else}
  <div class="board">
    {#each columns as col (col.v)}
      <section class="column">
        <h2>{col.l} <span class="muted">{col.items.length}</span></h2>
        {#each col.items as p (p.id)}
          <a class="card" href={`#/person/${p.id}`}>
            <span class="strong">{p.name}</span>
            <span class="muted">{orgById[p.organization_id]?.name ?? ''}</span>
          </a>
        {/each}
      </section>
    {/each}
  </div>
{/if}

<style>
  .scroll {
    overflow-x: auto;
    padding: 8px 16px 24px;
  }
  table {
    min-width: 860px;
  }
  .notice {
    margin: 16px 24px 0;
    padding: 8px 12px;
    border-radius: 8px;
    background: var(--accent-tint);
  }
  .add {
    margin: 16px 24px 0;
    max-width: 760px;
  }
  .inline {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .inline .field {
    flex: 1 1 auto;
    min-width: 0;
  }
  .board {
    display: flex;
    gap: 14px;
    padding: 16px 24px;
    overflow-x: auto;
    align-items: flex-start;
  }
  .column {
    flex: 0 0 220px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .column h2 {
    font-size: 12px;
    font-weight: 600;
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 10px 12px;
    border: 1px solid var(--sep);
    border-radius: 8px;
    color: var(--text);
  }
  .card:hover {
    background: var(--hover);
    color: var(--text);
  }
</style>
