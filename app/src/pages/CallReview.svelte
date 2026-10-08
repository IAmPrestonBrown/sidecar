<script lang="ts">
  import { onMount } from 'svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, mediaUrl, patch, post } from '../lib/api'
  import { label, mmss, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Call, CallReview, Evidence, Hypothesis, Person } from '../lib/types'

  let { id }: { id: string } = $props()

  let call = $state<Call | null>(null)
  let person = $state<Person | null>(null)
  let review = $state<CallReview | null>(null)
  let evidence = $state<Evidence[]>([])
  let hyps = $state<Record<string, Hypothesis>>({})
  let audio = $state<HTMLAudioElement | null>(null)
  let now = $state(0)
  let follow = $state(true)
  let error = $state('')
  let lines = $state<HTMLElement[]>([])

  $effect(() => {
    void app.version
    Promise.all([
      get<Call>(`${app.base}/c/calls/${id}`),
      get<CallReview>(`${app.base}/calls/${id}/review`),
      get<Evidence[]>(`${app.base}/c/evidence`),
      get<Hypothesis[]>(`${app.base}/c/hypotheses`),
    ])
      .then(async ([c, r, ev, h]) => {
        call = c
        review = r
        evidence = ev
          .filter((e) => e.call_id === id && e.review_status !== 'rejected')
          .sort((a, b) => (a.at_seconds ?? 0) - (b.at_seconds ?? 0))
        hyps = Object.fromEntries(h.map((x) => [x.id, x]))
        person = c.person_id ? await get<Person>(`${app.base}/c/people/${c.person_id}`) : null
      })
      .catch((e) => (error = String(e)))
  })

  const current = $derived(review ? review.segments.findLastIndex((s) => s.start <= now + 0.05) : -1)

  $effect(() => {
    if (follow && current >= 0) lines[current]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })

  function seek(seconds: number) {
    if (!audio) return
    audio.currentTime = Math.max(0, seconds - 1)
    audio.play().catch(() => {})
    follow = true
  }

  async function decide(e: Evidence, status: 'accepted' | 'rejected') {
    await patch(`${app.base}/c/evidence/${e.id}`, { review_status: status })
    app.changed()
  }

  onMount(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName
      if (!audio || e.metaKey || e.ctrlKey || ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(tag)) return
      if (e.key === ' ') {
        if (audio.paused) audio.play().catch(() => {})
        else audio.pause()
      } else if (e.key === 'ArrowLeft') audio.currentTime = Math.max(0, audio.currentTime - 10)
      else if (e.key === 'ArrowRight') audio.currentTime += 10
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
</script>

<Toolbar
  title={person?.name ?? call?.title ?? 'Call'}
  subtitle={call ? shortDate(call.started_at || call.created_at) : ''}
>
  {#snippet crumb()}<a href="#/calls">Calls</a><span class="faint">/</span>{/snippet}
  {#snippet actions()}
    {#if person}<a class="btn" href={`#/person/${person.id}`}>Open person</a>{/if}
    <button class="btn" onclick={() => post(`${app.base}/calls/${id}/reveal`)}>Show in Finder</button>
  {/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}

{#if review}
  <div class="player">
    {#if review.has_audio}
      <audio
        bind:this={audio}
        bind:currentTime={now}
        controls
        preload="metadata"
        src={mediaUrl(`${app.base}/calls/${id}/audio`)}
      ></audio>
    {:else}
      <span class="muted">No audio was saved for this call.</span>
    {/if}
    <span class="muted">Space play or pause · ← → 10 seconds</span>
  </div>

  <div class="split">
    <section class="transcript" aria-label="Transcript" onwheel={() => (follow = false)}>
      {#if review.transcript_source === 'live'}
        <p class="note muted">Live transcript. The final transcript was not made for this call.</p>
      {/if}
      {#each review.segments as s, i (i)}
        <button class="line" class:now={i === current} bind:this={lines[i]} onclick={() => seek(s.start + 1)}>
          <span class="time num">{mmss(s.start)}</span>
          <span class="who">{s.label}</span>
          <span class="text">{s.text}</span>
        </button>
      {:else}
        <p class="muted">No transcript for this call.</p>
      {/each}
    </section>

    <aside>
      <section>
        <h2>Marks</h2>
        {#each review.marks as m, i (i)}
          <button class="item" onclick={() => seek(m.at - 60)}>
            <span class="time num">{mmss(m.at)}</span>
            <span class="stack">
              <span class="strong">{m.headline}</span>
              {#if m.claim}<span>{m.claim}</span>{/if}
              {#if m.unknown}<span class="muted">Unknown: {m.unknown}</span>{/if}
            </span>
          </button>
        {:else}<p class="muted">No marks.</p>{/each}
      </section>

      <section>
        <h2>Evidence</h2>
        {#each evidence as e (e.id)}
          <div class="ev">
            <button class="item" onclick={() => e.at_seconds != null && seek(e.at_seconds)}>
              <span class="time num">{e.at_seconds != null ? mmss(e.at_seconds) : ''}</span>
              <span class="stack">
                <span>{e.quote ? `“${e.quote}”` : e.note}</span>
                <span class="muted">
                  {label(e.type)}
                  {#each e.links as l (l.hypothesis_id)}
                    · <span class={l.stance}>{label(l.stance)} {hyps[l.hypothesis_id]?.code}</span>
                  {/each}
                </span>
              </span>
            </button>
            {#if e.review_status === 'proposed'}
              <div class="decide">
                <button class="btn small" onclick={() => decide(e, 'rejected')}>Reject</button>
                <button class="btn small primary" onclick={() => decide(e, 'accepted')}>Accept</button>
              </div>
            {:else}
              <span class="muted accepted">Accepted</span>
            {/if}
          </div>
        {:else}<p class="muted">No evidence from this call.</p>{/each}
      </section>

      {#if review.asks.length}
        <section>
          <h2>Suggested questions</h2>
          {#each review.asks as a, i (i)}
            <button class="item" onclick={() => seek(a.at)}>
              <span class="time num">{mmss(a.at)}</span><span>{a.ask}</span>
            </button>
          {/each}
        </section>
      {/if}
    </aside>
  </div>
{/if}

<style>
  .player {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 14px;
    padding: 12px 24px;
    border-bottom: 1px solid var(--sep);
    position: sticky;
    top: 0;
    background: var(--bg);
    z-index: 1;
  }
  audio {
    flex: 1 1 360px;
    max-width: 640px;
  }
  .split {
    display: flex;
    flex-wrap: wrap;
    flex: 1 1 auto;
    min-height: 0;
  }
  .transcript {
    flex: 999 1 460px;
    min-width: 0;
    max-width: 820px;
    padding: 12px 16px 40px;
    display: flex;
    flex-direction: column;
  }
  .note {
    margin: 4px 8px 8px;
  }
  .line {
    display: grid;
    grid-template-columns: 48px 110px minmax(0, 1fr);
    gap: 10px;
    padding: 6px 8px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--text);
    font: inherit;
    line-height: 1.5;
    text-align: left;
    cursor: pointer;
    user-select: text;
  }
  .line:hover {
    background: var(--hover);
  }
  .line.now {
    background: var(--accent-tint);
  }
  .time {
    color: var(--muted);
    font-size: 12px;
    padding-top: 2px;
  }
  .who {
    color: var(--muted);
    font-size: 12px;
    font-weight: 600;
    padding-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  aside {
    flex: 1 1 300px;
    max-width: 400px;
    border-left: 1px solid var(--sep);
    background: var(--panel);
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }
  aside section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  h2 {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 4px;
  }
  .item {
    display: grid;
    grid-template-columns: 44px minmax(0, 1fr);
    gap: 8px;
    padding: 6px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--text);
    font: inherit;
    line-height: 1.4;
    text-align: left;
    cursor: pointer;
  }
  .item:hover {
    background: var(--hover);
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .ev {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--sep-soft);
  }
  .decide {
    display: flex;
    justify-content: flex-end;
    gap: 6px;
  }
  .accepted {
    align-self: flex-end;
    font-size: 12px;
  }
</style>
