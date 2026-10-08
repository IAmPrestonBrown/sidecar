<script lang="ts">
  let { name }: { name: string } = $props()
</script>

<svg
  width="16"
  height="16"
  viewBox="0 0 16 16"
  fill="none"
  stroke="currentColor"
  stroke-width="1.4"
  aria-hidden="true"
>
  {#if name === 'today'}
    <rect x="2" y="3" width="12" height="11" rx="2" /><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" />
  {:else if name === 'inbox'}
    <path d="M2 9.5l1.8-6h8.4l1.8 6v3.5H2z" /><path d="M2 9.5h3.5l1 1.5h3l1-1.5H14" />
  {:else if name === 'hypotheses'}
    <path d="M3 3.5h10M3 8h10M3 12.5h6" />
  {:else if name === 'evidence'}
    <path d="M3 4.5h4v4H4.5L3 11zM9 4.5h4v4h-2.5L9 11z" />
  {:else if name === 'brief'}
    <path d="M4 1.5h5.5L12.5 4.5v10h-8.5z" /><path d="M9.5 1.5v3h3M6 8h4.5M6 10.5h4.5" />
  {:else if name === 'queue'}
    <rect x="1.5" y="3.5" width="13" height="9" rx="1.5" /><path d="M2 4.5l6 4.5 6-4.5" />
  {:else if name === 'people'}
    <circle cx="8" cy="5.5" r="2.8" /><path d="M2.5 14c.8-2.8 3-4.2 5.5-4.2s4.7 1.4 5.5 4.2" />
  {:else if name === 'organizations'}
    <path d="M2.5 14V3.5h6.5V14M9 7h4.5v7M1.5 14h13" /><path d="M4.5 6h2.5M4.5 8.5h2.5M4.5 11h2.5" />
  {:else if name === 'find'}
    <circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" />
  {:else if name === 'calls'}
    <path
      d="M3.5 2h2.5l1.2 3-1.6 1.2a8 8 0 003.7 3.7L10.5 8.3l3 1.2V12a1.5 1.5 0 01-1.6 1.5C7 13.2 2.8 9 2.5 4.1A1.5 1.5 0 013.5 2z"
    />
  {:else if name === 'settings'}
    <circle cx="8" cy="8" r="2.2" /><path
      d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"
    />
  {:else if name === 'chevron'}
    <path d="M6 4l4 4-4 4" />
  {/if}
</svg>
