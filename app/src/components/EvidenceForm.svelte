<script lang="ts">
  import { untrack } from 'svelte'
  import { EVIDENCE_BASIS, EVIDENCE_TYPES, STANCES } from '../lib/labels'
  import type { Evidence, Hypothesis, Person, Stance } from '../lib/types'

  type Draft = Pick<Evidence, 'quote' | 'note' | 'type' | 'basis' | 'person_id' | 'links'>

  let {
    initial,
    hypotheses,
    people,
    submitLabel = 'Save',
    onsubmit,
    oncancel,
  }: {
    initial: Draft
    hypotheses: Hypothesis[]
    people: Person[]
    submitLabel?: string
    onsubmit: (draft: Draft) => void
    oncancel: () => void
  } = $props()

  let draft = $state<Draft>(untrack(() => structuredClone($state.snapshot(initial)) as Draft))
  let addHyp = $state('')

  const unlinked = $derived(hypotheses.filter((h) => !draft.links.some((l) => l.hypothesis_id === h.id)))
  const byId = $derived(Object.fromEntries(hypotheses.map((h) => [h.id, h])))
  const solutionLinked = $derived(draft.links.some((l) => byId[l.hypothesis_id]?.kind === 'solution'))

  function addLink() {
    if (!addHyp) return
    draft.links = [...draft.links, { hypothesis_id: addHyp, stance: 'supports' as Stance }]
    addHyp = ''
  }

  function removeLink(id: string) {
    draft.links = draft.links.filter((l) => l.hypothesis_id !== id)
  }
</script>

<form
  class="form-grid"
  onsubmit={(e) => {
    e.preventDefault()
    onsubmit(draft)
  }}
>
  <label for="ef-quote">Quote</label>
  <textarea
    id="ef-quote"
    class="field"
    rows="3"
    bind:value={draft.quote}
    placeholder="Their exact words, if any"></textarea>
  <label for="ef-note">Note</label>
  <input id="ef-note" class="field" bind:value={draft.note} />
  <label for="ef-person">Person</label>
  <select id="ef-person" class="select" bind:value={draft.person_id}>
    <option value="">None</option>
    {#each people as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
  </select>
  <label for="ef-type">Type</label>
  <select id="ef-type" class="select" style="width: 200px" bind:value={draft.type}>
    {#each EVIDENCE_TYPES as [v, l] (v)}<option value={v}>{l}</option>{/each}
  </select>
  <label for="ef-basis">Basis</label>
  <select id="ef-basis" class="select" style="width: 200px" bind:value={draft.basis}>
    {#each EVIDENCE_BASIS as [v, l] (v)}<option value={v}>{l}</option>{/each}
  </select>
  <span class="label" style="align-self: start; padding-top: 4px">Hypotheses</span>
  <div class="links">
    {#each draft.links as link (link.hypothesis_id)}
      <div class="link">
        <span class="strong code">{byId[link.hypothesis_id]?.code ?? '?'}</span>
        <span class="grow">{byId[link.hypothesis_id]?.title ?? ''}</span>
        <label class="sr-only" for={`st-${link.hypothesis_id}`}>Stance</label>
        <select id={`st-${link.hypothesis_id}`} class={`select ${link.stance}`} bind:value={link.stance}>
          {#each STANCES as [v, l] (v)}<option value={v}>{l}</option>{/each}
        </select>
        <button type="button" class="link-btn" onclick={() => removeLink(link.hypothesis_id)}>Remove</button>
      </div>
    {/each}
    {#if unlinked.length}
      <div class="link">
        <label class="sr-only" for="ef-add">Add hypothesis</label>
        <select id="ef-add" class="select" bind:value={addHyp}>
          <option value="">Add hypothesis…</option>
          {#each unlinked as h (h.id)}<option value={h.id}>{h.code} {h.title}</option>{/each}
        </select>
        <button type="button" class="btn small" disabled={!addHyp} onclick={addLink}>Add</button>
      </div>
    {/if}
    {#if solutionLinked}
      <p class="muted">Linked to a solution hypothesis. Problem evidence is not evidence for a solution.</p>
    {/if}
  </div>
  <span></span>
  <span class="buttons">
    <button type="button" class="btn" onclick={oncancel}>Cancel</button>
    <button type="submit" class="btn primary" disabled={!draft.quote.trim() && !draft.note.trim()}
      >{submitLabel}</button
    >
  </span>
</form>

<style>
  .links {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .link {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .code {
    width: 28px;
  }
  .grow {
    flex: 1 1 auto;
    min-width: 0;
  }
  .buttons {
    display: flex;
    gap: 8px;
  }
  select.supports {
    color: var(--supports);
  }
  select.contradicts {
    color: var(--contradicts);
  }
  select.mixed {
    color: var(--mixed);
  }
</style>
