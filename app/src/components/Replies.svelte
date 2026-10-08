<script lang="ts">
  import { get, post } from '../lib/api'
  import { autosize } from '../lib/autosize'
  import { shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Message, Person, ProjectMeta } from '../lib/types'

  const STAGES: [string, string][] = [
    ['', 'Keep the current stage'],
    ['interested', 'Interested'],
    ['scheduling', 'Scheduling'],
    ['confirmed', 'Confirmed'],
    ['replied', 'Replied, needs an answer'],
    ['declined', 'Declined'],
    ['do_not_contact', 'Do not contact'],
  ]

  let replies = $state<Message[]>([])
  let people = $state<Record<string, Person>>({})
  let choice = $state<Record<string, string>>({})
  let drafts = $state<Record<string, string>>({})
  let writing = $state<Record<string, boolean>>({})
  let sender = $state('')
  let error = $state('')

  $effect(() => {
    void app.version
    Promise.all([
      get<Message[]>(`${app.base}/c/messages`),
      get<Person[]>(`${app.base}/c/people`),
      get<ProjectMeta>(app.base),
    ])
      .then(([m, p, meta]) => {
        sender = meta.email.sender_name
        replies = m
          .filter((x) => x.kind === 'reply' && !x.triaged)
          .sort((a, b) => a.received_at.localeCompare(b.received_at))
        people = Object.fromEntries(p.map((x) => [x.id, x]))
      })
      .catch((e) => (error = String(e)))
  })

  function startWriting(reply: Message) {
    const first = people[reply.person_id]?.first_name || ''
    drafts[reply.id] ??= `Hi ${first},\n\n\n\nThanks,\n${sender}`
    writing[reply.id] = true
  }

  async function respond(reply: Message) {
    error = ''
    try {
      await post(`${app.base}/replies/${reply.id}/respond`, {
        body: drafts[reply.id],
        stage: choice[reply.id] ?? '',
      })
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }

  async function done(reply: Message) {
    error = ''
    try {
      await post(`${app.base}/replies/${reply.id}/triage`, { stage: choice[reply.id] ?? '' })
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }
</script>

{#if replies.length || error}
  <section class="replies" aria-label="Replies">
    <h2>Replies <span class="muted">{replies.length}</span></h2>
    {#if error}<div class="error-banner">{error}</div>{/if}
    {#each replies as r (r.id)}
      {@const person = people[r.person_id]}
      <article class="group">
        <header>
          <span class="strong">
            {#if person}<a href={`#/person/${person.id}`}>{person.name}</a>{:else}{r.from_address}{/if}
          </span>
          {#if r.bounce}<span class="contradicts">Bounced</span>{/if}
          {#if r.auto_reply}<span class="mixed">Automatic reply</span>{/if}
          <span class="muted when">{shortDate(r.received_at)}</span>
        </header>
        <div class="muted selectable">{r.from_address} · {r.subject}</div>
        <p class="body selectable">{r.body}</p>
        {#if writing[r.id]}
          <label class="sr-only" for={`resp-${r.id}`}>Your response</label>
          <textarea
            id={`resp-${r.id}`}
            class="field response"
            rows="6"
            bind:value={drafts[r.id]}
            use:autosize={drafts[r.id]}></textarea>
        {/if}
        <footer>
          <label class="sr-only" for={`stage-${r.id}`}>Move to stage</label>
          <select id={`stage-${r.id}`} class="select" bind:value={choice[r.id]}>
            {#each STAGES as [v, l] (v)}<option value={v}>{l}</option>{/each}
          </select>
          {#if writing[r.id]}
            <button class="btn" onclick={() => (writing[r.id] = false)}>Cancel</button>
            <button class="btn primary" disabled={!drafts[r.id]?.trim()} onclick={() => respond(r)}
              >Add to review queue</button
            >
          {:else}
            <button class="btn" onclick={() => done(r)}>Done</button>
            {#if !r.bounce}<button class="btn primary" onclick={() => startWriting(r)}>Reply…</button>{/if}
          {/if}
        </footer>
      </article>
    {/each}
  </section>
{/if}

<style>
  .replies {
    padding: 16px 24px 8px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-width: 860px;
    border-bottom: 1px solid var(--sep);
  }
  h2 {
    font-size: 13px;
    font-weight: 600;
  }
  article {
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  header,
  footer {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .when {
    margin-left: auto;
  }
  .response {
    font-size: 13px;
    line-height: 1.5;
    overflow: hidden;
  }
  .body {
    white-space: pre-wrap;
    line-height: 1.45;
    max-height: 240px;
    overflow: auto;
  }
</style>
