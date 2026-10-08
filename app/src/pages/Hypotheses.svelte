<script lang="ts">
  import Toolbar from '../components/Toolbar.svelte'
  import { get, post } from '../lib/api'
  import { label, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Evidence, Hypothesis, Tally } from '../lib/types'

  let hyps = $state<Hypothesis[]>([])
  let tallies = $state<Record<string, Tally>>({})
  let lastEvidence = $state<Record<string, string>>({})
  let adding = $state(false)
  let draft = $state({ code: '', title: '', statement: '', kind: 'problem' })
  let error = $state('')

  async function load() {
    const [h, t, ev] = await Promise.all([
      get<Hypothesis[]>(`${app.base}/c/hypotheses`),
      get<Record<string, Tally>>(`${app.base}/tallies`),
      get<Evidence[]>(`${app.base}/c/evidence`),
    ])
    hyps = h.sort((a, b) => a.sort - b.sort)
    tallies = t
    const last: Record<string, string> = {}
    for (const e of ev) {
      if (e.review_status !== 'accepted') continue
      for (const l of e.links)
        if (!last[l.hypothesis_id] || e.created_at > last[l.hypothesis_id])
          last[l.hypothesis_id] = e.created_at
    }
    lastEvidence = last
  }

  $effect(() => {
    void app.version
    load().catch((e) => (error = String(e)))
  })

  const groups = $derived([
    { title: 'Problem', items: hyps.filter((h) => h.kind === 'problem') },
    {
      title: 'Solution',
      note: 'Not steered toward in interviews',
      items: hyps.filter((h) => h.kind === 'solution'),
    },
    { title: 'Competing explanation', items: hyps.filter((h) => h.kind === 'competing') },
  ])

  function startAdd() {
    const next = hyps.filter((h) => /^H\d+$/.test(h.code)).length + 1
    draft = { code: `H${next}`, title: '', statement: '', kind: 'problem' }
    adding = true
  }

  async function save() {
    error = ''
    try {
      await post(`${app.base}/c/hypotheses`, {
        ...draft,
        sort: hyps.length,
        history: [{ text: 'Created' }],
      })
      adding = false
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }

  const n = (t: Tally | undefined, s: 'supports' | 'contradicts' | 'mixed') =>
    t ? t[s].strong + t[s].weak : 0
</script>

<Toolbar title="Hypotheses" subtitle={`${hyps.filter((h) => h.kind !== 'competing').length} hypotheses`}>
  {#snippet actions()}
    <button class="btn primary" onclick={startAdd}>Add hypothesis</button>
  {/snippet}
</Toolbar>

<div class="body">
  {#if error}<div class="error-banner">{error}</div>{/if}

  {#if adding}
    <form
      class="add group"
      onsubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      <div class="form-grid" style="padding: 14px">
        <label for="h-code">Code</label>
        <input id="h-code" class="field" style="width: 80px" bind:value={draft.code} />
        <label for="h-title">Short name</label>
        <input id="h-title" class="field" bind:value={draft.title} />
        <label for="h-st">Statement</label>
        <textarea id="h-st" class="field" rows="3" bind:value={draft.statement}></textarea>
        <label for="h-kind">Kind</label>
        <select id="h-kind" class="select" style="width: 200px" bind:value={draft.kind}>
          <option value="problem">Problem</option>
          <option value="solution">Solution</option>
          <option value="competing">Competing explanation</option>
        </select>
        <span></span>
        <span style="display: flex; gap: 8px">
          <button type="button" class="btn" onclick={() => (adding = false)}>Cancel</button>
          <button type="submit" class="btn primary" disabled={!draft.statement.trim()}>Add</button>
        </span>
      </div>
    </form>
  {/if}

  <div class="scroll">
    <table class="list">
      <thead>
        <tr>
          <th style="width: 44px">Code</th>
          <th>Statement</th>
          <th style="width: 96px">Status</th>
          <th style="width: 76px; text-align: right">Supports</th>
          <th style="width: 88px; text-align: right">Contradicts</th>
          <th style="width: 60px; text-align: right">Mixed</th>
          <th style="width: 56px; text-align: right">Orgs</th>
          <th style="width: 96px">Last evidence</th>
        </tr>
      </thead>
      {#each groups as g (g.title)}
        {#if g.items.length}
          <tbody>
            <tr class="group-row">
              <td colspan="8"
                >{g.title}{#if g.note}<span class="muted">&nbsp;· {g.note}</span>{/if}</td
              >
            </tr>
            {#each g.items as h (h.id)}
              <tr class="clickable" onclick={() => app.go('hypothesis', h.id)}>
                <td class="strong muted">{h.code}</td>
                <td
                  ><a href={`#/hypothesis/${h.id}`} class="stmt"
                    ><span class="strong">{h.title}</span>{#if h.title}<br />{/if}<span class="muted"
                      >{h.statement}</span
                    ></a
                  ></td
                >
                <td>{label(h.status)}</td>
                <td
                  class="num"
                  class:supports={n(tallies[h.id], 'supports') > 0}
                  class:faint={!n(tallies[h.id], 'supports')}
                  style="text-align: right">{n(tallies[h.id], 'supports')}</td
                >
                <td
                  class="num"
                  class:contradicts={n(tallies[h.id], 'contradicts') > 0}
                  class:faint={!n(tallies[h.id], 'contradicts')}
                  style="text-align: right">{n(tallies[h.id], 'contradicts')}</td
                >
                <td
                  class="num"
                  class:mixed={n(tallies[h.id], 'mixed') > 0}
                  class:faint={!n(tallies[h.id], 'mixed')}
                  style="text-align: right">{n(tallies[h.id], 'mixed')}</td
                >
                <td class="num" style="text-align: right">{tallies[h.id]?.organizations ?? 0}</td>
                <td class="muted">{shortDate(lastEvidence[h.id]) || '—'}</td>
              </tr>
            {/each}
          </tbody>
        {/if}
      {/each}
    </table>
    <p class="muted foot">
      Counts include accepted evidence only. Orgs counts independent organizations; two people at one company
      count once.
    </p>
  </div>
</div>

<style>
  .body {
    padding: 16px 24px 32px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .scroll {
    overflow-x: auto;
  }
  table {
    min-width: 760px;
  }
  .group-row td {
    padding-top: 18px;
    font-weight: 600;
    border-top: 0;
    border-bottom: 1px solid var(--sep);
  }
  .stmt {
    color: var(--text);
    display: block;
    line-height: 1.4;
  }
  .stmt:hover {
    color: var(--text);
  }
  .foot {
    margin-top: 14px;
  }
  .add {
    max-width: 760px;
  }
</style>
