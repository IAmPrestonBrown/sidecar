<script lang="ts">
  import Toolbar from '../components/Toolbar.svelte'
  import { del, get, patch, post } from '../lib/api'
  import { label } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Organization, Person } from '../lib/types'

  let orgs = $state<Organization[]>([])
  let people = $state<Person[]>([])
  let selectedId = $state('')
  let q = $state('')
  let newName = $state('')
  let confirmDelete = $state(false)
  let error = $state('')

  $effect(() => {
    void app.version
    Promise.all([get<Organization[]>(`${app.base}/c/organizations`), get<Person[]>(`${app.base}/c/people`)])
      .then(([o, p]) => {
        orgs = o.sort((a, b) => a.name.localeCompare(b.name))
        people = p
      })
      .catch((e) => (error = String(e)))
  })

  const peopleByOrg = $derived(
    people.reduce<Record<string, Person[]>>((acc, p) => {
      ;(acc[p.organization_id] ??= []).push(p)
      return acc
    }, {}),
  )
  const rows = $derived(
    orgs.filter(
      (o) => !q || [o.name, o.domain, ...o.aliases].join(' ').toLowerCase().includes(q.toLowerCase()),
    ),
  )
  const current = $derived(orgs.find((o) => o.id === selectedId))
  const staff = $derived(current ? (peopleByOrg[current.id] ?? []) : [])

  $effect(() => {
    void selectedId
    confirmDelete = false
  })

  async function save(fields: Partial<Organization>) {
    if (!current) return
    error = ''
    try {
      await patch(`${app.base}/c/organizations/${current.id}`, fields)
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }

  function text(key: 'name' | 'domain' | 'website' | 'notes') {
    return (e: Event) => {
      const value = (e.currentTarget as HTMLInputElement).value.trim()
      if (current && current[key] !== value) save({ [key]: value })
    }
  }

  function aliases(e: Event) {
    const list = (e.currentTarget as HTMLInputElement).value
      .split(',')
      .map((a) => a.trim())
      .filter(Boolean)
    if (current && list.join(',') !== current.aliases.join(',')) save({ aliases: list })
  }

  async function add() {
    const name = newName.trim()
    if (!name) return
    error = ''
    try {
      const org = await post<Organization>(`${app.base}/c/organizations`, { name })
      newName = ''
      selectedId = org.id
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }

  async function remove() {
    if (!current) return
    await del(`${app.base}/c/organizations/${current.id}`)
    selectedId = ''
    app.changed()
  }
</script>

<Toolbar title="Organizations" subtitle={`${rows.length} of ${orgs.length}`}>
  {#snippet actions()}
    <label class="sr-only" for="o-q">Search organizations</label>
    <input id="o-q" type="search" class="field search" placeholder="Search" bind:value={q} />
    <form
      class="inline"
      onsubmit={(e) => {
        e.preventDefault()
        add()
      }}
    >
      <label class="sr-only" for="o-new">New organization</label>
      <input id="o-new" class="field" placeholder="New organization" bind:value={newName} />
      <button class="btn" type="submit" disabled={!newName.trim()}>Add</button>
    </form>
  {/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}

<div class="split">
  <div class="scroll">
    <table class="list">
      <thead>
        <tr>
          <th>Name</th>
          <th style="width: 180px">Segment</th>
          <th style="width: 70px">People</th>
          <th style="width: 130px">Contacted before</th>
        </tr>
      </thead>
      <tbody>
        {#each rows as o (o.id)}
          <tr class="clickable" class:selected={o.id === selectedId} onclick={() => (selectedId = o.id)}>
            <td
              ><button class="link-btn strong" onclick={() => (selectedId = o.id)}>{o.name}</button
              >{#if o.domain}<br /><span class="muted">{o.domain}</span>{/if}</td
            >
            <td>{o.segment}</td>
            <td class="num">{peopleByOrg[o.id]?.length ?? 0}</td>
            <td class:mixed={o.already_contacted}>{o.already_contacted ? 'Yes' : ''}</td>
          </tr>
        {:else}
          <tr><td colspan="4" class="muted">No organizations match.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if current}
    {#key current.id}
      <aside aria-label="Organization">
        <div class="form">
          <label for="o-name">Name</label>
          <input id="o-name" class="field" value={current.name} onblur={text('name')} />
          <label for="o-alias">Other names</label>
          <input
            id="o-alias"
            class="field"
            placeholder="Comma separated"
            value={current.aliases.join(', ')}
            onblur={aliases}
          />
          <label for="o-domain">Email domain</label>
          <input id="o-domain" class="field" value={current.domain} onblur={text('domain')} />
          <label for="o-web">Website</label>
          <input id="o-web" class="field" value={current.website} onblur={text('website')} />
          <label for="o-seg">Segment</label>
          <select
            id="o-seg"
            class="select"
            value={current.segment}
            onchange={(e) => save({ segment: (e.currentTarget as HTMLSelectElement).value })}
          >
            <option value="">Not known</option>
            {#each app.segments as s (s)}<option value={s}>{s}</option>{/each}
          </select>
          <label class="check"
            ><input
              type="checkbox"
              checked={current.already_contacted}
              onchange={(e) => save({ already_contacted: (e.currentTarget as HTMLInputElement).checked })}
            /> Contacted before this project</label
          >
          <label for="o-notes">Notes</label>
          <textarea id="o-notes" class="field" rows="4" value={current.notes} onblur={text('notes')}
          ></textarea>
        </div>

        <section>
          <h2>People</h2>
          {#each staff as p (p.id)}
            <a href={`#/person/${p.id}`}>{p.name}</a>
            <span class="muted">{p.role}{p.role ? ' · ' : ''}{label(p.stage)}</span>
          {:else}
            <p class="muted">Nobody listed here yet.</p>
          {/each}
          {#if staff.length > 1}
            <p class="mixed">People at the same organization are not independent sources.</p>
          {/if}
        </section>

        <div class="actions">
          {#if staff.length}
            <span class="muted">Move or delete its people before deleting this organization.</span>
          {:else if confirmDelete}
            <span class="muted">Delete {current.name}?</span>
            <button class="btn" onclick={() => (confirmDelete = false)}>Cancel</button>
            <button class="btn danger" onclick={remove}>Delete</button>
          {:else}
            <button class="btn" onclick={() => (confirmDelete = true)}>Delete…</button>
          {/if}
        </div>
      </aside>
    {/key}
  {/if}
</div>

<style>
  .inline {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .split {
    display: flex;
    flex-wrap: wrap;
    flex: 1 1 auto;
    min-height: 0;
  }
  .scroll {
    flex: 999 1 480px;
    min-width: 0;
    overflow-x: auto;
    padding: 8px 16px 24px;
  }
  tr.selected td {
    background: var(--selected);
  }
  aside {
    flex: 1 1 280px;
    max-width: 360px;
    border-left: 1px solid var(--sep);
    background: var(--panel);
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .form label:not(.check) {
    margin-top: 4px;
    color: var(--muted);
  }
  .check {
    display: flex;
    gap: 6px;
    align-items: center;
    margin-top: 8px;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  h2 {
    font-size: 13px;
    font-weight: 600;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
</style>
