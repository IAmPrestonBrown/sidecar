<script lang="ts">
  import { onMount } from 'svelte'
  import Toolbar from '../components/Toolbar.svelte'
  import { get, patch, put } from '../lib/api'
  import { app } from '../lib/state.svelte'
  import type { ProjectMeta } from '../lib/types'

  type Doc = 'brief' | 'outreach_brief'

  let doc = $state<Doc>('brief')
  let text = $state('')
  let saved = $state('')
  let meta = $state<ProjectMeta | null>(null)
  let phrase = $state('')
  let keyterms = $state('')
  let status = $state('')
  let error = $state('')

  async function loadDoc(d: Doc) {
    const res = await get<{ text: string }>(`${app.base}/docs/${d}`)
    text = res.text
    saved = res.text
  }

  $effect(() => {
    loadDoc(doc).catch((e) => (error = String(e)))
  })

  $effect(() => {
    void app.version
    get<ProjectMeta>(app.base)
      .then((m) => {
        meta = m
        keyterms = m.coach.keyterms.join(', ')
      })
      .catch((e) => (error = String(e)))
  })

  const dirty = $derived(text !== saved)

  async function save() {
    if (!dirty) return
    await put(`${app.base}/docs/${doc}`, { text })
    saved = text
    status = `Saved ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
  }

  async function switchTo(d: Doc) {
    await save()
    doc = d
  }

  async function saveMeta(fields: Partial<ProjectMeta>) {
    meta = await patch<ProjectMeta>(app.base, fields)
  }

  function addPhrase() {
    const p = phrase.trim()
    if (!p || !meta || meta.banned_phrases.includes(p)) return
    saveMeta({ banned_phrases: [...meta.banned_phrases, p] })
    phrase = ''
  }

  onMount(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      save()
    }
  })
</script>

<Toolbar title="Brief" subtitle={dirty ? 'Edited' : status}>
  {#snippet actions()}
    <div class="segmented" role="tablist" aria-label="Document">
      <button role="tab" aria-selected={doc === 'brief'} onclick={() => switchTo('brief')}
        >Research brief</button
      >
      <button role="tab" aria-selected={doc === 'outreach_brief'} onclick={() => switchTo('outreach_brief')}
        >Outreach brief</button
      >
    </div>
    <button class="btn" disabled={!dirty} onclick={save}>Save</button>
  {/snippet}
</Toolbar>

{#if error}<div class="error-banner" style="margin: 16px 24px">{error}</div>{/if}

<div class="layout">
  <div class="doc">
    <p class="muted">
      {doc === 'brief'
        ? 'The live coach reads this brief. Hypotheses are managed on the Hypotheses page.'
        : 'The email writer follows this brief: who to contact, the template, and the writing rules.'}
    </p>
    <label class="sr-only" for="doc-text">Document text</label>
    <textarea id="doc-text" class="field editor" bind:value={text} onblur={save} spellcheck="true"></textarea>
  </div>

  {#if meta}
    <aside>
      <section>
        <h2>Phrases emails must not use</h2>
        <p class="muted">Drafts containing these are flagged in the review queue.</p>
        <ul class="chips">
          {#each meta.banned_phrases as p (p)}
            <li class="chip">
              {p}
              <button
                class="x"
                aria-label={`Remove ${p}`}
                onclick={() =>
                  meta && saveMeta({ banned_phrases: meta.banned_phrases.filter((x) => x !== p) })}>×</button
              >
            </li>
          {:else}<li class="muted">None.</li>{/each}
        </ul>
        <form
          class="row"
          onsubmit={(e) => {
            e.preventDefault()
            addPhrase()
          }}
        >
          <label class="sr-only" for="add-phrase">Add phrase</label>
          <input id="add-phrase" class="field" placeholder="Add phrase" bind:value={phrase} />
          <button class="btn small" type="submit">Add</button>
        </form>
      </section>
      <section>
        <h2>Coach for this project</h2>
        <div class="form-grid" style="grid-template-columns: 80px minmax(0, 1fr)">
          <label for="act">Activity</label>
          <select
            id="act"
            class="select"
            value={meta.coach.activity}
            onchange={(e) =>
              saveMeta({ coach: { ...meta!.coach, activity: (e.currentTarget as HTMLSelectElement).value } })}
          >
            <option value="quiet">Quiet</option>
            <option value="balanced">Balanced</option>
            <option value="active">Active</option>
          </select>
          <label for="kt">Keyterms</label>
          <textarea
            id="kt"
            class="field"
            rows="4"
            bind:value={keyterms}
            onblur={() =>
              saveMeta({
                coach: {
                  ...meta!.coach,
                  keyterms: keyterms
                    .split(',')
                    .map((k) => k.trim())
                    .filter(Boolean),
                },
              })}></textarea>
        </div>
      </section>
    </aside>
  {/if}
</div>

<style>
  .layout {
    display: flex;
    flex-wrap: wrap;
    gap: 28px;
    padding: 20px 24px 24px;
    flex: 1 1 auto;
    min-height: 0;
  }
  .doc {
    flex: 999 1 520px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .editor {
    flex: 1 1 auto;
    min-height: 480px;
    font-size: 14px;
    line-height: 1.55;
    padding: 14px 16px;
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
    gap: 8px;
  }
  h2 {
    font-size: 13px;
    font-weight: 600;
  }
  .chips {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .x {
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    padding: 0 2px;
  }
  .row {
    display: flex;
    gap: 6px;
  }
  .row .field {
    flex: 1 1 auto;
    min-width: 0;
  }
</style>
