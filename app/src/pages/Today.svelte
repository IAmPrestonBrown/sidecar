<script lang="ts">
  import Icon from '../components/Icon.svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, post } from '../lib/api'
  import { label, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Hypothesis, Organization, OutreachMetrics, Overview, Tally } from '../lib/types'

  let overview = $state<Overview | null>(null)
  let metrics = $state<OutreachMetrics | null>(null)
  let hyps = $state<Hypothesis[]>([])
  let tallies = $state<Record<string, Tally>>({})
  let orgs = $state<Record<string, Organization>>({})
  let exported = $state('')
  let error = $state('')

  $effect(() => {
    void app.version
    Promise.all([
      get<Overview>(`${app.base}/overview`),
      get<Hypothesis[]>(`${app.base}/c/hypotheses`),
      get<Record<string, Tally>>(`${app.base}/tallies`),
      get<Organization[]>(`${app.base}/c/organizations`),
      get<OutreachMetrics>(`${app.base}/outreach/metrics`),
    ])
      .then(([o, h, t, og, m]) => {
        overview = o
        metrics = m
        hyps = h.sort((a, b) => a.sort - b.sort)
        tallies = t
        orgs = Object.fromEntries(og.map((x) => [x.id, x]))
      })
      .catch((e) => (error = String(e)))
  })

  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })

  async function exportProject() {
    const out = await post<{ json: string; markdown: string }>(`${app.base}/export`)
    exported = out.markdown
  }

  function total(t: Tally | undefined, stance: 'supports' | 'contradicts' | 'mixed'): number {
    return t ? t[stance].strong + t[stance].weak : 0
  }
</script>

<Toolbar title="Today" subtitle={today}>
  {#snippet actions()}
    <button class="btn" onclick={exportProject}>Export project</button>
  {/snippet}
</Toolbar>

<div class="grid">
  {#if error}<div class="error-banner">{error}</div>{/if}
  {#if exported}
    <div class="note selectable">Exported to <code>{exported}</code> and the matching .json file.</div>
  {/if}

  <section>
    <h2>Waiting for you</h2>
    <div class="group">
      <a class="row" href="#/inbox">
        <span class="big num">{overview?.evidence_to_review ?? 0}</span>
        <span class="stack"
          ><span class="strong">Evidence to review</span><span class="muted"
            >From calls, before it counts</span
          ></span
        >
        <span class="chev"><Icon name="chevron" /></span>
      </a>
      <a class="row" href="#/queue">
        <span class="big num">{overview?.drafts_to_review ?? 0}</span>
        <span class="stack"
          ><span class="strong">Emails to approve</span><span class="muted">Review queue</span></span
        >
        <span class="chev"><Icon name="chevron" /></span>
      </a>
      <a class="row" href="#/people">
        <span class="big num">{overview?.prospects_to_review ?? 0}</span>
        <span class="stack"
          ><span class="strong">Prospects ready for review</span><span class="muted"
            >People marked ready for review</span
          ></span
        >
        <span class="chev"><Icon name="chevron" /></span>
      </a>
    </div>
  </section>

  <section>
    <h2>Interview leads</h2>
    {#if overview && overview.leads_open.length}
      <div class="group">
        {#each overview.leads_open as p (p.id)}
          <a class="row" href={`#/person/${p.id}`}>
            <span class="stack">
              <span class="strong">{p.name}</span>
              <span class="muted">{orgs[p.organization_id]?.name ?? ''} · {label(p.stage)}</span>
              {#if p.next_action}<span>{p.next_action}</span>{/if}
            </span>
            <span class="chev"><Icon name="chevron" /></span>
          </a>
        {/each}
      </div>
    {:else}
      <p class="empty">No open leads.</p>
    {/if}
  </section>

  <section>
    <h2>Follow-ups due</h2>
    {#if metrics && metrics.follow_ups_due.length}
      <div class="group">
        {#each metrics.follow_ups_due as f (f.id)}
          <a class="row" href={`#/person/${f.id}`}>
            <span class="stack">
              <span class="strong">{f.name}</span>
              <span class="muted">{f.next_action || 'Follow up'} · due {shortDate(f.due)}</span>
            </span>
            <span class="chev"><Icon name="chevron" /></span>
          </a>
        {/each}
      </div>
    {:else}
      <p class="empty">Nothing due.</p>
    {/if}
  </section>

  {#if metrics}
    <section>
      <h2>Outreach</h2>
      <div class="group metrics">
        {#each [['Emails sent', metrics.emails_sent], ['Contacted', metrics.contacted], ['Replied', metrics.replied], ['Positive', metrics.positive], ['Confirmed', metrics.confirmed], ['Completed', metrics.completed]] as [name, value] (name)}
          <div class="metric">
            <span class="big num">{value}</span>
            <span class="muted">{name}</span>
          </div>
        {/each}
      </div>
      {#if metrics.completed_organizations.length}
        <p class="muted pad">Completed at {metrics.completed_organizations.join(', ')}</p>
      {/if}
    </section>
  {/if}

  <section class="wide">
    <h2>Hypotheses</h2>
    <div class="group">
      {#each hyps as h (h.id)}
        <a class="row" href={`#/hypothesis/${h.id}`}>
          <span class="code">{h.code}</span>
          <span class="grow">{h.title || h.statement}</span>
          <span
            class="num"
            class:supports={total(tallies[h.id], 'supports') > 0}
            class:faint={!total(tallies[h.id], 'supports')}>Supports {total(tallies[h.id], 'supports')}</span
          >
          <span
            class="num"
            class:contradicts={total(tallies[h.id], 'contradicts') > 0}
            class:faint={!total(tallies[h.id], 'contradicts')}
            >Contradicts {total(tallies[h.id], 'contradicts')}</span
          >
          <span class="muted num orgs"
            >{tallies[h.id]?.organizations ?? 0} {tallies[h.id]?.organizations === 1 ? 'org' : 'orgs'}</span
          >
        </a>
      {/each}
    </div>
  </section>
</div>

<style>
  .grid {
    padding: 24px;
    max-width: 1100px;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 24px;
    align-items: start;
  }
  .wide {
    grid-column: 1 / -1;
  }
  .error-banner,
  .note {
    grid-column: 1 / -1;
  }
  .note {
    padding: 10px 14px;
    border-radius: 8px;
    background: var(--panel);
    border: 1px solid var(--sep);
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  h2 {
    margin: 0 4px;
    font-size: 13px;
    font-weight: 600;
  }
  .big {
    min-width: 28px;
    font-size: 20px;
    font-weight: 600;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .chev {
    margin-left: auto;
    color: var(--faint);
    display: inline-flex;
  }
  .metrics {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
    padding: 14px;
  }
  .metric {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .pad {
    margin: 0 4px;
  }
  .code {
    width: 26px;
    font-weight: 600;
    color: var(--muted);
  }
  .grow {
    flex: 1 1 auto;
    min-width: 0;
  }
  .orgs {
    width: 52px;
    text-align: right;
  }
  code {
    font-family: var(--mono);
    font-size: 12px;
  }
</style>
