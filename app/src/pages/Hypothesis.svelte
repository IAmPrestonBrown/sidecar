<script lang="ts">
  import EvidenceForm from '../components/EvidenceForm.svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, patch, post } from '../lib/api'
  import { HYPOTHESIS_STATUS, isStrong, label, mmss, shortDate } from '../lib/labels'
  import { autosize } from '../lib/autosize'
  import { app } from '../lib/state.svelte'
  import type { Evidence, Hypothesis, Organization, Person, Tally } from '../lib/types'

  let { id }: { id: string } = $props()

  let hyp = $state<Hypothesis | null>(null)
  let all = $state<Hypothesis[]>([])
  let tally = $state<Tally | null>(null)
  let evidence = $state<Evidence[]>([])
  let people = $state<Person[]>([])
  let orgs = $state<Record<string, Organization>>({})
  let statement = $state('')
  let notes = $state('')
  let adding = $state(false)
  let error = $state('')

  async function load() {
    const [h, hs, t, ev, ps, os] = await Promise.all([
      get<Hypothesis>(`${app.base}/c/hypotheses/${id}`),
      get<Hypothesis[]>(`${app.base}/c/hypotheses`),
      get<Record<string, Tally>>(`${app.base}/tallies`),
      get<Evidence[]>(`${app.base}/c/evidence`),
      get<Person[]>(`${app.base}/c/people`),
      get<Organization[]>(`${app.base}/c/organizations`),
    ])
    hyp = h
    all = hs.sort((a, b) => a.sort - b.sort)
    tally = t[id] ?? null
    evidence = ev.filter((e) => e.review_status === 'accepted' && e.links.some((l) => l.hypothesis_id === id))
    people = ps
    orgs = Object.fromEntries(os.map((o) => [o.id, o]))
    statement = h.statement
    notes = h.notes
  }

  $effect(() => {
    void app.version
    load().catch((e) => (error = String(e)))
  })

  const personById = $derived(Object.fromEntries(people.map((p) => [p.id, p])))

  function stanceOf(e: Evidence): string {
    return e.links.find((l) => l.hypothesis_id === id)?.stance ?? ''
  }

  function source(e: Evidence): string {
    const p = personById[e.person_id]
    const o = orgs[e.organization_id || p?.organization_id || '']
    return [p?.name, o?.name].filter(Boolean).join(' · ')
  }

  async function save(fields: Partial<Hypothesis>, historyText = '') {
    if (!hyp) return
    const history = historyText
      ? [...hyp.history, { at: new Date().toISOString(), text: historyText }]
      : undefined
    hyp = await patch<Hypothesis>(`${app.base}/c/hypotheses/${id}`, history ? { ...fields, history } : fields)
    app.changed()
  }

  async function addEvidence(draft: Partial<Evidence>) {
    await post(`${app.base}/c/evidence`, { ...draft, source: 'manual', review_status: 'accepted' })
    adding = false
    app.changed()
  }

  const stances = ['supports', 'contradicts', 'mixed'] as const
</script>

<Toolbar title={hyp?.code ?? ''}>
  {#snippet crumb()}<a href="#/hypotheses">Hypotheses</a><span class="faint">/</span>{/snippet}
  {#snippet actions()}
    {#if hyp}
      <label for="h-status" class="muted">Status</label>
      <select
        id="h-status"
        class="select"
        value={hyp.status}
        onchange={(e) =>
          save(
            { status: (e.currentTarget as HTMLSelectElement).value as Hypothesis['status'] },
            `Status set to ${label((e.currentTarget as HTMLSelectElement).value)}`,
          )}
      >
        {#each HYPOTHESIS_STATUS as [v, l] (v)}<option value={v}>{l}</option>{/each}
      </select>
      <button class="btn" onclick={() => (adding = true)}>Add evidence</button>
    {/if}
  {/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}

{#if hyp}
  <div class="layout">
    <div class="main">
      <div class="stack">
        <span class="muted"
          >{hyp.kind === 'competing'
            ? 'Competing explanation'
            : `${hyp.kind === 'solution' ? 'Solution' : 'Problem'} hypothesis`}{hyp.title &&
          hyp.kind !== 'competing'
            ? ` · ${hyp.title}`
            : ''}</span
        >
        <label class="sr-only" for="h-statement">Statement</label>
        <textarea
          id="h-statement"
          class="statement"
          rows="2"
          use:autosize={statement}
          bind:value={statement}
          onblur={() => statement !== hyp?.statement && save({ statement }, 'Statement edited')}></textarea>
      </div>

      {#if tally}
        <div class="tally group">
          {#each stances as s (s)}
            <div class="cell">
              <div class="caption">{label(s).toUpperCase()}</div>
              <div class={`count num ${tally[s].strong + tally[s].weak ? s : 'faint'}`}>
                {tally[s].strong + tally[s].weak}
              </div>
              <div class="muted">{tally[s].strong} strong · {tally[s].weak} weak</div>
            </div>
          {/each}
          <div class="cell">
            <div class="caption">INDEPENDENT ORGS</div>
            <div class="count num">{tally.organizations}</div>
            <div class="muted">organizations behind the evidence</div>
          </div>
        </div>
      {/if}

      {#if adding}
        <div class="group" style="padding: 14px">
          <EvidenceForm
            initial={{
              quote: '',
              note: '',
              type: 'behavior',
              basis: 'statement',
              person_id: '',
              links: [{ hypothesis_id: id, stance: 'supports' }],
            }}
            hypotheses={all}
            {people}
            submitLabel="Add evidence"
            onsubmit={addEvidence}
            oncancel={() => (adding = false)}
          />
        </div>
      {/if}

      {#each stances as s (s)}
        {@const items = evidence.filter((e) => stanceOf(e) === s)}
        <section>
          <h2>{label(s)} <span class="muted">{items.length}</span></h2>
          {#each items as e (e.id)}
            <article class="item">
              <p class="quote selectable">{e.quote ? `“${e.quote}”` : e.note}</p>
              {#if e.quote && e.note}<p class="muted">{e.note}</p>{/if}
              <div class="meta">
                <span>{source(e) || 'No person'}</span>
                <span>{shortDate(e.created_at)}</span>
                <span class="strong" style="color: var(--text)"
                  >{label(e.type)} · {isStrong(e.type, e.basis) ? 'strong' : 'weak'}</span
                >
                <span>{label(e.basis)}</span>
                {#if e.at_seconds != null}<span class="right">{mmss(e.at_seconds)} in call</span>{/if}
              </div>
            </article>
          {:else}
            <p class="muted">None yet.</p>
          {/each}
        </section>
      {/each}
    </div>

    <aside>
      <section>
        <h2>Notes</h2>
        <label class="sr-only" for="h-notes">Notes</label>
        <textarea
          id="h-notes"
          class="field"
          rows="8"
          bind:value={notes}
          onblur={() => notes !== hyp?.notes && save({ notes })}></textarea>
      </section>
      <section>
        <h2>History</h2>
        <ol>
          {#each [...hyp.history].reverse() as entry, i (i)}
            <li><span class="muted">{shortDate(entry.at)}</span> · {entry.text}</li>
          {/each}
        </ol>
      </section>
    </aside>
  </div>
{/if}

<style>
  .layout {
    display: flex;
    flex-wrap: wrap;
    gap: 32px;
    padding: 24px;
  }
  .main {
    flex: 999 1 520px;
    min-width: 0;
    max-width: 820px;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }
  aside {
    flex: 1 1 260px;
    max-width: 360px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .statement {
    overflow: hidden;
    font-size: 20px;
    font-weight: 600;
    line-height: 1.35;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 6px;
    margin: 0 -6px;
    background: transparent;
    resize: vertical;
  }
  .statement:hover {
    border-color: var(--sep);
  }
  .statement:focus {
    border-color: var(--accent);
    outline: 3px solid var(--accent-tint);
  }
  .tally {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  }
  .cell {
    padding: 12px 14px;
  }
  .cell + .cell {
    border-left: 1px solid var(--sep-soft);
  }
  .count {
    font-size: 22px;
    font-weight: 600;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  h2 {
    font-size: 13px;
    font-weight: 600;
  }
  .item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px 14px;
    border: 1px solid var(--sep);
    border-radius: 10px;
  }
  .quote {
    font-size: 14px;
    line-height: 1.45;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    color: var(--muted);
  }
  .right {
    margin-left: auto;
  }
  ol {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>
