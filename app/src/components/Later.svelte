<script lang="ts">
  import Toolbar from './Toolbar.svelte'

  let { title, points }: { title: string; points: string[] } = $props()
</script>

<Toolbar {title} />
<div class="body">
  <p class="strong">This section isn't available yet. It will cover:</p>
  <ul>
    {#each points as point (point)}<li>{point}</li>{/each}
  </ul>
</div>

<style>
  .body {
    padding: 24px;
    max-width: 640px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  ul {
    margin: 0;
    padding-left: 20px;
    color: var(--text-2);
    line-height: 1.6;
  }
</style>
