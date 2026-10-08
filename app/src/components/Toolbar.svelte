<script lang="ts">
  import type { Snippet } from 'svelte'

  let {
    title,
    subtitle = '',
    crumb,
    actions,
  }: { title: string; subtitle?: string; crumb?: Snippet; actions?: Snippet } = $props()
</script>

<header data-tauri-drag-region>
  {#if crumb}{@render crumb()}{/if}
  <h1>{title}</h1>
  {#if subtitle}<span class="muted">{subtitle}</span>{/if}
  <div class="actions">
    {#if actions}{@render actions()}{/if}
  </div>
</header>

<style>
  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 12px;
    min-height: 52px;
    padding: 10px 24px;
    border-bottom: 1px solid var(--sep);
    flex: none;
  }
  h1 {
    font-size: 15px;
    font-weight: 600;
  }
  .actions {
    margin-left: auto;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
</style>
