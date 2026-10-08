<script lang="ts">
  import { get } from '../lib/api'
  import { call } from '../lib/call.svelte'
  import { app, type Page } from '../lib/state.svelte'
  import type { Overview } from '../lib/types'
  import Icon from './Icon.svelte'

  let overview = $state<Overview | null>(null)

  $effect(() => {
    void app.version
    if (!app.slug) return
    get<Overview>(`${app.base}/overview`)
      .then((o) => (overview = o))
      .catch(() => (overview = null))
  })

  const inboxCount = $derived(overview ? overview.evidence_to_review + overview.replies_to_review : 0)
  const queueCount = $derived(overview ? overview.drafts_to_review : 0)

  const sections: { title: string; items: { page: Page; label: string; also?: Page[] }[] }[] = [
    {
      title: '',
      items: [
        { page: 'today', label: 'Today' },
        { page: 'inbox', label: 'Inbox' },
      ],
    },
    {
      title: 'Research',
      items: [
        { page: 'hypotheses', label: 'Hypotheses', also: ['hypothesis'] },
        { page: 'evidence', label: 'Evidence' },
        { page: 'brief', label: 'Brief' },
      ],
    },
    {
      title: 'Outreach',
      items: [
        { page: 'queue', label: 'Review queue' },
        { page: 'people', label: 'People', also: ['person'] },
        { page: 'organizations', label: 'Organizations' },
        { page: 'find', label: 'Find prospects' },
      ],
    },
    { title: 'Calls', items: [{ page: 'calls', label: 'Calls' }] },
  ]

  function active(page: Page, also: Page[] = []): boolean {
    return app.route.page === page || also.includes(app.route.page)
  }

  function count(page: Page): number {
    if (page === 'inbox') return inboxCount
    if (page === 'queue') return queueCount
    return 0
  }
</script>

<nav aria-label="Sidebar">
  <div class="titlebar" data-tauri-drag-region></div>
  <label class="sr-only" for="project-picker">Project</label>
  <select
    id="project-picker"
    class="project"
    value={app.slug}
    onchange={(e) => app.selectProject((e.currentTarget as HTMLSelectElement).value)}
  >
    {#each app.projects as p (p.slug)}
      <option value={p.slug}>{p.name}</option>
    {/each}
  </select>

  {#each sections as section (section.title)}
    {#if section.title}<div class="section">{section.title}</div>{/if}
    {#each section.items as item (item.page)}
      <a
        href={`#/${item.page}`}
        class="item"
        class:active={active(item.page, item.also)}
        aria-current={active(item.page, item.also) ? 'page' : undefined}
      >
        <span class="icon"><Icon name={item.page} /></span>
        <span>{item.label}</span>
        {#if count(item.page) > 0}<span class="count num">{count(item.page)}</span>{/if}
        {#if item.page === 'calls' && call.live}<span class="live" title="Call in progress"></span>{/if}
      </a>
    {/each}
  {/each}

  <div class="spacer"></div>
  <a href="#/settings" class="item" class:active={active('settings')}>
    <span class="icon"><Icon name="settings" /></span>
    <span>Settings</span>
  </a>
</nav>

<style>
  nav {
    display: flex;
    flex-direction: column;
    gap: 2px;
    height: 100%;
    padding: 0 10px 14px;
    background: var(--sidebar);
    border-right: 1px solid var(--sep);
    overflow-y: auto;
  }
  .titlebar {
    height: 44px;
    flex: none;
  }
  .project {
    height: 30px;
    margin: 0 0 10px;
    padding: 0 8px;
    border: 1px solid var(--field-border);
    border-radius: 6px;
    background: var(--field);
    font-weight: 600;
  }
  .section {
    margin: 14px 8px 4px;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted);
  }
  .item {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 28px;
    padding: 0 8px;
    border-radius: 6px;
    color: var(--text);
  }
  .item:hover {
    background: var(--hover);
    color: var(--text);
  }
  .item.active {
    background: var(--selected);
    font-weight: 600;
  }
  .icon {
    display: inline-flex;
    color: var(--link);
  }
  .count {
    margin-left: auto;
    font-size: 12px;
    color: var(--muted);
    font-weight: 400;
  }
  .spacer {
    flex: 1 1 auto;
    min-height: 24px;
  }
  .live {
    margin-left: auto;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--contradicts);
  }
</style>
