<script lang="ts">
  import Toolbar from '../components/Toolbar.svelte'
  import { del, get, patch, post } from '../lib/api'
  import { EMAIL_CONFIDENCE, SCORE_DIMENSIONS, STAGES, label, shortDate } from '../lib/labels'
  import { app } from '../lib/state.svelte'
  import type { Evidence, Interview, Message, Organization, Person, Score, Source } from '../lib/types'

  let { id }: { id: string } = $props()

  let person = $state<Person | null>(null)
  let orgs = $state<Organization[]>([])
  let others = $state<Person[]>([])
  let evidence = $state<Evidence[]>([])
  let interviews = $state<Interview[]>([])
  let messages = $state<Message[]>([])
  let newSource = $state<Source>({ url: '', title: '', quote: '' })
  let confirmDelete = $state(false)
  let error = $state('')

  $effect(() => {
    void app.version
    Promise.all([
      get<Person>(`${app.base}/c/people/${id}`),
      get<Organization[]>(`${app.base}/c/organizations`),
      get<Person[]>(`${app.base}/c/people`),
      get<Evidence[]>(`${app.base}/c/evidence`),
      get<Interview[]>(`${app.base}/c/interviews`),
      get<Message[]>(`${app.base}/c/messages`),
    ])
      .then(([p, o, all, ev, iv, ms]) => {
        person = p
        orgs = o.sort((a, b) => a.name.localeCompare(b.name))
        others = all.filter((x) => x.organization_id === p.organization_id && x.id !== p.id)
        evidence = ev.filter((e) => e.person_id === p.id)
        interviews = iv.filter((i) => i.person_id === p.id)
        messages = ms
          .filter((m) => m.person_id === p.id)
          .sort((a, b) => a.created_at.localeCompare(b.created_at))
      })
      .catch((e) => (error = String(e)))
  })

  const org = $derived(orgs.find((o) => o.id === person?.organization_id))

  async function save(fields: Partial<Person>) {
    error = ''
    try {
      person = await patch<Person>(`${app.base}/c/people/${id}`, fields)
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }

  function field(key: keyof Person) {
    return (e: Event) => {
      const value = (e.currentTarget as HTMLInputElement).value
      if (person && person[key] !== value) save({ [key]: value } as Partial<Person>)
    }
  }

  function setScore(dim: string, part: keyof Score, value: string) {
    if (!person) return
    const cur = person.scores[dim] ?? { level: 'medium', reason: '' }
    save({ scores: { ...person.scores, [dim]: { ...cur, [part]: value } } })
  }

  function addSource() {
    if (!person || !newSource.url.trim()) return
    save({ sources: [...person.sources, { ...newSource, url: newSource.url.trim() }] })
    newSource = { url: '', title: '', quote: '' }
  }

  async function draftEmail() {
    error = ''
    try {
      const res = await post<{ created: string[]; errors: Record<string, string> }>(
        `${app.base}/outreach/drafts`,
        { person_ids: [id] },
      )
      if (res.created.length) app.go('queue')
      else error = Object.values(res.errors).join('; ')
    } catch (e) {
      error = String(e)
    }
  }

  async function addInterview() {
    await post(`${app.base}/c/interviews`, { person_id: id, time_zone: person?.time_zone ?? '' })
    app.changed()
  }

  async function saveInterview(iv: Interview, fields: Partial<Interview>) {
    error = ''
    try {
      await patch(`${app.base}/c/interviews/${iv.id}`, fields)
      app.changed()
    } catch (e) {
      error = String(e)
    }
  }

  async function removeInterview(iv: Interview) {
    await del(`${app.base}/c/interviews/${iv.id}`)
    app.changed()
  }

  /** Proposed times are stored one per line in the editor. */
  function times(e: Event): string[] {
    return (e.currentTarget as HTMLTextAreaElement).value
      .split('\n')
      .map((t) => t.trim())
      .filter(Boolean)
  }

  async function remove() {
    await del(`${app.base}/c/people/${id}`)
    app.changed()
    app.go('people')
  }
</script>

<Toolbar title={person?.name ?? ''}>
  {#snippet crumb()}<a href="#/people">People</a><span class="faint">/</span>{/snippet}
  {#snippet actions()}
    {#if confirmDelete}
      <span class="muted">Delete this person?</span>
      <button class="btn" onclick={() => (confirmDelete = false)}>Cancel</button>
      <button class="btn danger" onclick={remove}>Delete</button>
    {:else}
      <button class="btn" onclick={() => (confirmDelete = true)}>Delete…</button>
      <button class="btn" disabled={person?.do_not_contact} onclick={draftEmail}>Draft email</button>
      <button class="btn" onclick={() => app.go('calls', id)}>Start call…</button>
    {/if}
  {/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}

{#if person}
  <div class="layout">
    <div class="main">
      <section>
        <h2>Outreach</h2>
        <div class="form-grid">
          <label for="stage">Stage</label>
          <select
            id="stage"
            class="select"
            style="width: 220px"
            value={person.stage}
            onchange={(e) => save({ stage: (e.currentTarget as HTMLSelectElement).value })}
          >
            {#each STAGES as [v, l] (v)}<option value={v}>{l}</option>{/each}
          </select>
          <label for="next">Next action</label>
          <input id="next" class="field" value={person.next_action} onblur={field('next_action')} />
          <label for="due">Due</label>
          <input
            id="due"
            type="date"
            class="field"
            style="width: 160px"
            value={person.next_action_due}
            onchange={field('next_action_due')}
          />
          <label for="prio">Priority</label>
          <select
            id="prio"
            class="select"
            style="width: 120px"
            value={person.priority}
            onchange={(e) =>
              save({ priority: (e.currentTarget as HTMLSelectElement).value as Person['priority'] })}
          >
            <option value="high">High</option><option value="medium">Medium</option><option value="low"
              >Low</option
            >
          </select>
          <span class="label">Do not contact</span>
          <label class="check"
            ><input
              type="checkbox"
              checked={person.do_not_contact}
              onchange={(e) => save({ do_not_contact: (e.currentTarget as HTMLInputElement).checked })}
            /> Never email or call</label
          >
        </div>
      </section>

      <section>
        <h2>Contact</h2>
        <div class="form-grid">
          <label for="email">Email</label>
          <span class="inline">
            <input id="email" class="field" value={person.email} onblur={field('email')} />
            <label class="sr-only" for="conf">Email confidence</label>
            <select
              id="conf"
              class="select"
              value={person.email_confidence}
              onchange={(e) => save({ email_confidence: (e.currentTarget as HTMLSelectElement).value })}
            >
              {#each EMAIL_CONFIDENCE as [v, l] (v)}<option value={v}>{l}</option>{/each}
            </select>
          </span>
          {#if person.email_confidence === 'inferred_direct'}
            <span></span>
            <p class="mixed">
              Inferred from a company pattern, not verified. Sending will ask you to confirm.
            </p>
          {/if}
          <label for="phone">Business phone</label>
          <input id="phone" class="field" value={person.phone} onblur={field('phone')} />
          <label for="web">Website</label>
          <input id="web" class="field" value={person.website} onblur={field('website')} />
          <label for="tz">Time zone</label>
          <input
            id="tz"
            class="field"
            style="width: 220px"
            placeholder="America/Chicago"
            value={person.time_zone}
            onblur={field('time_zone')}
          />
        </div>
      </section>

      <section>
        <h2>Research</h2>
        <div class="form-grid">
          <label for="role">Role</label>
          <input id="role" class="field" value={person.role} onblur={field('role')} />
          <label for="seg">Segment</label>
          <select
            id="seg"
            class="select"
            style="width: 260px"
            value={person.segment}
            onchange={(e) => save({ segment: (e.currentTarget as HTMLSelectElement).value })}
          >
            <option value="">Not known</option>
            {#each app.segments as s (s)}<option value={s}>{s}</option>{/each}
          </select>
          <label for="segb">Segment basis</label>
          <input
            id="segb"
            class="field"
            placeholder="What source shows this?"
            value={person.segment_basis}
            onblur={field('segment_basis')}
          />
          <label for="bg">Background</label>
          <textarea id="bg" class="field" rows="2" value={person.background} onblur={field('background')}
          ></textarea>
          <label for="useful">Why useful</label>
          <textarea id="useful" class="field" rows="2" value={person.why_useful} onblur={field('why_useful')}
          ></textarea>
          <label for="recept">Why receptive <span class="faint">(inference)</span></label>
          <textarea
            id="recept"
            class="field"
            rows="2"
            value={person.why_receptive}
            onblur={field('why_receptive')}></textarea>
        </div>
      </section>

      <section>
        <h2>Scores <span class="muted">· shown separately, never combined</span></h2>
        <div class="scores">
          {#each SCORE_DIMENSIONS as [dim, name] (dim)}
            {@const s = person.scores[dim]}
            <label for={`sc-${dim}`} class="muted">{name}</label>
            <select
              id={`sc-${dim}`}
              class="select"
              value={s?.level ?? ''}
              onchange={(e) => setScore(dim, 'level', (e.currentTarget as HTMLSelectElement).value)}
            >
              <option value="" disabled>—</option>
              <option value="high">High</option><option value="medium">Medium</option><option value="low"
                >Low</option
              >
            </select>
            <input
              class="field"
              aria-label={`${name} reason`}
              placeholder="Reason"
              value={s?.reason ?? ''}
              onblur={(e) => setScore(dim, 'reason', (e.currentTarget as HTMLInputElement).value)}
            />
          {/each}
        </div>
      </section>

      <section>
        <h2>Sources</h2>
        {#each person.sources as src, i (i)}
          <div class="source">
            <span class="selectable"
              ><a href={src.url} target="_blank" rel="noreferrer">{src.title || src.url}</a></span
            >
            {#if src.quote}<span class="muted">“{src.quote}”</span>{/if}
            <button
              class="link-btn"
              onclick={() => person && save({ sources: person.sources.filter((_, j) => j !== i) })}
              >Remove</button
            >
          </div>
        {:else}
          <p class="muted">No sources yet. Every research claim should link to one.</p>
        {/each}
        <form
          class="inline"
          onsubmit={(e) => {
            e.preventDefault()
            addSource()
          }}
        >
          <input class="field" aria-label="Source URL" placeholder="URL" bind:value={newSource.url} />
          <input class="field" aria-label="Source title" placeholder="Title" bind:value={newSource.title} />
          <input
            class="field"
            aria-label="Quoted text"
            placeholder="Quoted text"
            bind:value={newSource.quote}
          />
          <button class="btn small" type="submit">Add</button>
        </form>
      </section>

      <section>
        <h2>Interviews</h2>
        {#each interviews as iv (iv.id)}
          <div class="group interview">
            <div class="form-grid">
              <label for={`pt-${iv.id}`}>Proposed times</label>
              <textarea
                id={`pt-${iv.id}`}
                class="field"
                rows="2"
                placeholder="One per line, for example Tue Oct 14, 2:00 pm"
                value={iv.proposed_times.join('\n')}
                onblur={(e) => saveInterview(iv, { proposed_times: times(e) })}></textarea>
              <label for={`tz-${iv.id}`}>Time zone</label>
              <input
                id={`tz-${iv.id}`}
                class="field"
                style="width: 220px"
                placeholder="America/Chicago"
                value={iv.time_zone}
                onblur={(e) => saveInterview(iv, { time_zone: (e.currentTarget as HTMLInputElement).value })}
              />
              <label for={`ct-${iv.id}`}>Confirmed</label>
              <input
                id={`ct-${iv.id}`}
                type="datetime-local"
                class="field"
                style="width: 220px"
                value={iv.confirmed_time}
                onchange={(e) =>
                  saveInterview(iv, { confirmed_time: (e.currentTarget as HTMLInputElement).value })}
              />
              <label for={`m-${iv.id}`}>Method</label>
              <select
                id={`m-${iv.id}`}
                class="select"
                style="width: 160px"
                value={iv.method}
                onchange={(e) =>
                  saveInterview(iv, {
                    method: (e.currentTarget as HTMLSelectElement).value as Interview['method'],
                  })}
              >
                <option value="">Not set</option>
                <option value="phone">Phone</option>
                <option value="video">Video</option>
                <option value="in_person">In person</option>
              </select>
              <label for={`d-${iv.id}`}>Details</label>
              <input
                id={`d-${iv.id}`}
                class="field"
                placeholder="Number or link"
                value={iv.details}
                onblur={(e) => saveInterview(iv, { details: (e.currentTarget as HTMLInputElement).value })}
              />
              <span class="label">Completed</span>
              <label class="check"
                ><input
                  type="checkbox"
                  checked={iv.completed}
                  onchange={(e) =>
                    saveInterview(iv, { completed: (e.currentTarget as HTMLInputElement).checked })}
                /> The interview happened</label
              >
              <label for={`o-${iv.id}`}>Outcome</label>
              <textarea
                id={`o-${iv.id}`}
                class="field"
                rows="2"
                value={iv.outcome}
                onblur={(e) => saveInterview(iv, { outcome: (e.currentTarget as HTMLTextAreaElement).value })}
              ></textarea>
              <span></span>
              <span><button class="link-btn" onclick={() => removeInterview(iv)}>Remove</button></span>
            </div>
          </div>
        {:else}
          <p class="muted">No interview scheduled.</p>
        {/each}
        <div><button class="btn small" onclick={addInterview}>Add interview</button></div>
      </section>

      <section>
        <h2>Notes</h2>
        <textarea class="field" rows="5" aria-label="Notes" value={person.notes} onblur={field('notes')}
        ></textarea>
      </section>
    </div>

    <aside>
      <section>
        <h2>Organization</h2>
        <label class="sr-only" for="org">Organization</label>
        <select
          id="org"
          class="select"
          value={person.organization_id}
          onchange={(e) => save({ organization_id: (e.currentTarget as HTMLSelectElement).value })}
        >
          <option value="">None</option>
          {#each orgs as o (o.id)}<option value={o.id}>{o.name}</option>{/each}
        </select>
        {#if org?.already_contacted}<p class="mixed">This organization was already contacted.</p>{/if}
        {#if others.length}
          <p class="muted">
            Others here: {others.map((o) => o.name).join(', ')}. They are not independent sources.
          </p>
        {/if}
      </section>
      <section>
        <h2>Evidence from {person.first_name || person.name}</h2>
        {#each evidence as e (e.id)}
          <p class="ev">“{e.quote || e.note}” <span class="muted">· {label(e.review_status)}</span></p>
        {:else}<p class="muted">None yet.</p>{/each}
      </section>
      <section>
        <h2>Emails</h2>
        {#each messages as m (m.id)}
          <p class="ev">
            {m.subject || '(no subject)'}
            <span class="muted">· {label(m.kind)} · {label(m.status)} · {shortDate(m.updated_at)}</span>
          </p>
        {:else}<p class="muted">None yet.</p>{/each}
      </section>
      <section>
        <h2>Record</h2>
        <p class="muted">
          Researched {person.researched_on || '—'} · added {shortDate(person.created_at)} · updated {shortDate(
            person.updated_at,
          )}
        </p>
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
    max-width: 780px;
    display: flex;
    flex-direction: column;
    gap: 26px;
  }
  aside {
    flex: 1 1 260px;
    max-width: 340px;
    display: flex;
    flex-direction: column;
    gap: 22px;
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
  .inline {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .inline .field {
    flex: 1 1 auto;
    min-width: 0;
  }
  .check {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .scores {
    display: grid;
    grid-template-columns: 200px 110px minmax(0, 1fr);
    gap: 8px 10px;
    align-items: center;
  }
  .source {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: baseline;
  }
  .source .link-btn {
    margin-left: auto;
  }
  .interview {
    padding: 14px;
  }
  .ev {
    line-height: 1.4;
  }
</style>
