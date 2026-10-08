<script lang="ts">
  import { post } from '../lib/api'
  import { app } from '../lib/state.svelte'
  import type { ImportPreview } from '../lib/types'

  let { onclose }: { onclose: () => void } = $props()

  let text = $state('')
  let preview = $state<ImportPreview | null>(null)
  let mapping = $state<Record<string, string>>({})
  let error = $state('')
  let busy = $state(false)

  const creating = $derived(preview ? preview.rows.filter((r) => r.action === 'create').length : 0)

  async function readFile(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0]
    if (!file) return
    text = await file.text()
    await load(null)
  }

  async function load(map: Record<string, string> | null) {
    error = ''
    if (!text.trim()) return
    try {
      preview = await post<ImportPreview>(`${app.base}/import/preview`, { csv: text, mapping: map })
      mapping = { ...preview.mapping }
    } catch (e) {
      error = String(e)
    }
  }

  function remap(header: string, target: string) {
    const next = { ...mapping }
    for (const [h, t] of Object.entries(next)) if (t === target && target) delete next[h]
    if (target) next[header] = target
    else delete next[header]
    load(next)
  }

  async function commit() {
    busy = true
    error = ''
    try {
      await post(`${app.base}/import/commit`, { csv: text, mapping })
      app.changed()
      onclose()
    } catch (e) {
      error = String(e)
    } finally {
      busy = false
    }
  }
</script>

<section class="group panel" aria-label="Import CSV">
  <div class="row">
    <span class="strong">Import from CSV</span>
    <span class="spacer"></span>
    <label class="btn file">
      Choose file…
      <input type="file" accept=".csv,text/csv" class="sr-only" onchange={readFile} />
    </label>
    <button class="btn" onclick={onclose}>Cancel</button>
  </div>

  {#if !preview}
    <label class="muted" for="csv-text">Or paste rows, with a header line first.</label>
    <textarea id="csv-text" class="field mono" rows="6" bind:value={text}></textarea>
    <div class="row">
      <span class="spacer"></span>
      <button class="btn" disabled={!text.trim()} onclick={() => load(null)}>Preview</button>
    </div>
  {:else}
    <div class="mapping">
      {#each preview.headers as header (header)}
        <label for={`map-${header}`} class="selectable">{header}</label>
        <select
          id={`map-${header}`}
          class="select"
          value={mapping[header] ?? ''}
          onchange={(e) => remap(header, (e.currentTarget as HTMLSelectElement).value)}
        >
          <option value="">Don't import</option>
          {#each preview.targets as t (t)}<option value={t}>{t.replace(/_/g, ' ')}</option>{/each}
        </select>
      {/each}
    </div>

    <div class="scroll">
      <table class="list">
        <thead>
          <tr>
            <th style="width: 48px">Line</th>
            <th>Name</th>
            <th>Organization</th>
            <th>Email</th>
            <th style="width: 72px">Action</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {#each preview.rows as row (row.line)}
            <tr class:skipped={row.action === 'skip'}>
              <td class="muted num">{row.line}</td>
              <td>{row.values.name ?? ''}</td>
              <td>{row.values.organization ?? ''}</td>
              <td>{row.values.email ?? ''}</td>
              <td>{row.action === 'create' ? 'Add' : 'Skip'}</td>
              <td class="mixed">{row.issues.join('. ')}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="muted">
      Imported addresses count as unverified until you mark them verified, and new people start as Discovered.
    </p>
    <div class="row">
      <button class="btn" onclick={() => (preview = null)}>Back</button>
      <span class="spacer"></span>
      <button class="btn primary" disabled={!creating || busy} onclick={commit}>
        Add {creating}
        {creating === 1 ? 'person' : 'people'}
      </button>
    </div>
  {/if}
  {#if error}<div class="error-banner">{error}</div>{/if}
</section>

<style>
  .panel {
    margin: 16px 24px 0;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
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
  .file {
    position: relative;
  }
  .mono {
    font-family: var(--mono);
    font-size: 12px;
  }
  .mapping {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 160px) minmax(140px, 180px));
    gap: 6px 10px;
    align-items: center;
  }
  .scroll {
    overflow-x: auto;
    max-height: 320px;
  }
  .skipped td {
    color: var(--muted);
  }
  .skipped td.mixed {
    color: var(--mixed);
  }
</style>
