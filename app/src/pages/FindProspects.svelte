<script lang="ts">
  import Toolbar from '../components/Toolbar.svelte'
  import { get, post } from '../lib/api'
  import { SCORE_DIMENSIONS, label, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { ResearchRun, Suggestion } from '../lib/types'

  let runs = $state<ResearchRun[]>([])
  let selectedId = $state('')
  let query = $state('')
  let count = $state(8)
  let error = $state('')
  let timer: ReturnType<typeof setTimeout> | undefined

  async function load() {
    clearTimeout(timer)
    runs = (await get<ResearchRun[]>(`${app.base}/c/research_runs`)).sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    )
    if (!runs.some((r) => r.id === selectedId)) selectedId = runs[0]?.id ?? ''
    if (runs.some((r) => r.status === 'running')) timer = setTimeout(() => load().catch(() => {}), 3000)
  }

  $effect(() => {
    void app.version
    load().catch((e) => (error = String(e)))
    return () => clearTimeout(timer)
  })

  const current = $derived(runs.find((r) => r.id === selectedId))
  const running = $derived(runs.some((r) => r.status === 'running'))
  const pending = $derived(current ? current.suggestions.filter((s) => s.status === 'pending').length : 0)

  async function start() {
    error = ''
    try {
      const run = await post<ResearchRun>(`${app.base}/research`, { query, count })
      selectedId = run.id
      await load()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  async function decide(index: number, accept: boolean) {
    if (!current) return
    error = ''
    try {
      await post(`${app.base}/research/${current.id}/decide`, { index, accept })
      app.changed()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  function confidence(s: Suggestion): string {
    if (!s.email) return 'No email found'
    return label(s.email_confidence)
  }
</script>

<Toolbar title="Find prospects" subtitle={current ? `${pending} to review` : ''} />

<div class="body">
  {#if error}<div class="error-banner">{error}</div>{/if}

  <form
    class="group ask"
    onsubmit={(e) => {
      e.preventDefault()
      start()
    }}
  >
    <label for="q" class="strong">Who should Claude look for?</label>
    <textarea
      id="q"
      class="field"
      rows="3"
      placeholder="For example: independent contract processors in Texas who work across several lenders"
      bind:value={query}></textarea>
    <div class="row">
      <label for="n" class="muted">Up to</label>
      <select id="n" class="select" bind:value={count}>
        {#each [5, 8, 12] as n (n)}<option value={n}>{n} people</option>{/each}
      </select>
      <span class="muted"
        >Uses your outreach brief and segments, and skips every organization already in this project.</span
      >
      <span class="spacer"></span>
      <button class="btn primary" type="submit" disabled={!query.trim() || running}>
        {running ? 'Searching…' : 'Search'}
      </button>
    </div>
  </form>

  {#if runs.length}
    <div class="split">
      <nav class="runs" aria-label="Research runs">
        {#each runs as r (r.id)}
          <button class="run" class:active={r.id === selectedId} onclick={() => (selectedId = r.id)}>
            <span class="text">{r.query}</span>
            <span class="meta">
              {shortDate(r.created_at)} ·
              {#if r.status === 'running'}searching…
              {:else if r.status === 'failed'}failed
              {:else}{r.suggestions.length} found · ${r.cost_usd.toFixed(2)}{/if}
            </span>
          </button>
        {/each}
      </nav>

      <section class="results" aria-label="Suggestions">
        {#if !current}
          <p class="muted">Select a run.</p>
        {:else if current.status === 'running'}
          <p class="muted">
            Claude is searching the web and reading sources. This usually takes a few minutes. You can leave
            this page.
          </p>
        {:else if current.status === 'failed'}
          <p class="contradicts selectable">The run failed: {current.error}</p>
        {:else}
          <p class="muted summary">
            {current.suggestions.length} suggestions from {current.searches} searches, ${current.cost_usd.toFixed(
              2,
            )}.
            {#if current.dropped}{current.dropped} more were already in this project or repeated an organization.{/if}
            {#if current.notes}<br />{current.notes}{/if}
          </p>
          {#each current.suggestions as s, i (i)}
            <article class="group card" class:done={s.status !== 'pending'}>
              <header>
                <span class="stack">
                  <span class="strong">{s.name}</span>
                  <span class="muted">{s.role}{s.role && s.organization ? ' · ' : ''}{s.organization}</span>
                </span>
                <span class="spacer"></span>
                {#if s.status === 'pending'}
                  <button class="btn" onclick={() => decide(i, false)}>Reject</button>
                  <button class="btn primary" onclick={() => decide(i, true)}>Add to People</button>
                {:else if s.status === 'added'}
                  <a href={`#/person/${s.person_id}`}>Added</a>
                {:else}
                  <span class="muted">Rejected</span>
                {/if}
              </header>

              <dl>
                <dt>Email</dt>
                <dd class:mixed={s.email && s.email_confidence !== 'verified_direct'}>
                  <span class="selectable">{s.email}</span>{s.email ? ' · ' : ''}{confidence(s)}
                </dd>
                {#if s.segment}<dt>Segment</dt>
                  <dd>{s.segment}{s.segment_basis ? `: ${s.segment_basis}` : ''}</dd>{/if}
                {#if s.background}<dt>Background</dt>
                  <dd>{s.background}</dd>{/if}
                <dt>Why useful</dt>
                <dd>{s.why_useful}</dd>
                <dt>Why receptive</dt>
                <dd>{s.why_receptive} <span class="faint">(inference)</span></dd>
              </dl>

              <div class="scores">
                {#each SCORE_DIMENSIONS as [key, name] (key)}
                  {@const sc = s.scores[key]}
                  {#if sc}
                    <span class="score" title={sc.reason}>
                      <span class="muted">{name}</span>
                      <span class={`level ${sc.level}`}>{sc.level}</span>
                    </span>
                  {/if}
                {/each}
              </div>

              <div class="sources">
                {#each s.sources as src, j (j)}
                  <div class="source selectable">
                    <a href={src.url} target="_blank" rel="noreferrer">{src.title || src.url}</a>
                    {#if src.quote}<span class="muted">“{src.quote}”</span>{/if}
                  </div>
                {/each}
              </div>
            </article>
          {:else}
            <p class="muted">No new prospects in this run.</p>
          {/each}
        {/if}
      </section>
    </div>
  {:else}
    <p class="muted empty-note">
      Each search proposes people with cited public sources, an honest email confidence, and five separate
      scores. Nobody is added to People until you approve them.
    </p>
  {/if}
</div>

<style>
  .body {
    padding: 16px 24px 40px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .ask {
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 920px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .spacer {
    flex: 1 1 auto;
  }
  .split {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    align-items: flex-start;
  }
  .runs {
    flex: 1 1 220px;
    max-width: 260px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .run {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 10px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .run:hover {
    background: var(--hover);
  }
  .run.active {
    background: var(--accent);
    color: var(--accent-text);
  }
  .run .text {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .run .meta {
    font-size: 12px;
    opacity: 0.75;
  }
  .results {
    flex: 999 1 520px;
    min-width: 0;
    max-width: 820px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .summary {
    line-height: 1.45;
  }
  .card {
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .card.done {
    opacity: 0.6;
  }
  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  dl {
    display: grid;
    grid-template-columns: 110px minmax(0, 1fr);
    gap: 4px 10px;
    margin: 0;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
    line-height: 1.45;
  }
  .scores {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .score {
    display: inline-flex;
    gap: 6px;
    padding: 3px 8px;
    border-radius: 6px;
    background: var(--chip);
    font-size: 12px;
    cursor: help;
  }
  .level {
    font-weight: 600;
  }
  .level.high {
    color: var(--supports);
  }
  .level.low {
    color: var(--muted);
  }
  .sources {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
  }
  .source {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .empty-note {
    max-width: 640px;
    line-height: 1.5;
  }
</style>
