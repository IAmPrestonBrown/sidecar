<script lang="ts">
  import { onMount } from 'svelte'
  import Later from './components/Later.svelte'
  import Sidebar from './components/Sidebar.svelte'
  import { listen } from '@tauri-apps/api/event'
  import { connect, inTauri } from './lib/api'
  import { call } from './lib/call.svelte'
  import { gmail } from './lib/gmail.svelte'
  import { app } from './lib/state.svelte'
  import Brief from './pages/Brief.svelte'
  import CallReview from './pages/CallReview.svelte'
  import Calls from './pages/Calls.svelte'
  import Evidence from './pages/Evidence.svelte'
  import Hypotheses from './pages/Hypotheses.svelte'
  import Hypothesis from './pages/Hypothesis.svelte'
  import Inbox from './pages/Inbox.svelte'
  import Organizations from './pages/Organizations.svelte'
  import People from './pages/People.svelte'
  import Person from './pages/Person.svelte'
  import ReviewQueue from './pages/ReviewQueue.svelte'
  import Settings from './pages/Settings.svelte'
  import Today from './pages/Today.svelte'

  let status = $state<'connecting' | 'ready' | 'failed'>('connecting')
  let error = $state('')

  onMount(async () => {
    try {
      await connect()
      await app.loadProjects()
      status = 'ready'
      await call.refresh()
      await gmail.refresh()
      if (inTauri()) {
        await listen('quit-blocked', () => {
          call.quitBlocked = true
          app.go('calls')
        })
      }
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
      status = 'failed'
    }
  })
</script>

{#if status === 'connecting'}
  <div class="center" data-tauri-drag-region><span class="muted">Starting…</span></div>
{:else if status === 'failed'}
  <div class="center" data-tauri-drag-region>
    <div class="failed">
      <p class="strong">Sidecar could not reach its engine.</p>
      <p class="muted selectable">{error}</p>
      <p class="muted">
        Check that <code>uv</code> is installed and that <code>uv run sidecar-engine</code> works in the project
        folder.
      </p>
    </div>
  </div>
{:else if app.projects.length === 0}
  <div class="center" data-tauri-drag-region>
    <div class="failed">
      <p class="strong">No projects yet.</p>
      <p class="muted">
        Run <code>uv run sidecar seed</code> in the project folder to create them from the briefs.
      </p>
    </div>
  </div>
{:else}
  <div class="shell">
    <Sidebar />
    <main>
      {#key `${app.slug}:${app.route.page}:${app.route.id}`}
        {#if app.route.page === 'today'}<Today />
        {:else if app.route.page === 'inbox'}<Inbox />
        {:else if app.route.page === 'hypotheses'}<Hypotheses />
        {:else if app.route.page === 'hypothesis'}<Hypothesis id={app.route.id} />
        {:else if app.route.page === 'evidence'}<Evidence />
        {:else if app.route.page === 'brief'}<Brief />
        {:else if app.route.page === 'people'}<People />
        {:else if app.route.page === 'person'}<Person id={app.route.id} />
        {:else if app.route.page === 'settings'}<Settings />
        {:else if app.route.page === 'queue'}<ReviewQueue />
        {:else if app.route.page === 'organizations'}<Organizations />
        {:else if app.route.page === 'find'}
          <Later
            title="Find prospects"
            points={[
              'Research runs with cited public sources and email confidence levels',
              'Five separate scores, never one combined score',
              'Already-contacted organizations excluded, counterexample segments included',
              'For now, add people by hand or with Import CSV on the People page',
            ]}
          />
        {:else if app.route.page === 'calls'}<Calls personId={app.route.id} />
        {:else if app.route.page === 'call'}<CallReview id={app.route.id} />
        {/if}
      {/key}
    </main>
  </div>
{/if}

<style>
  .shell {
    display: grid;
    grid-template-columns: 232px minmax(0, 1fr);
    height: 100%;
  }
  main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    height: 100%;
    overflow: auto;
    background: var(--bg);
  }
  .center {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg);
    padding: 24px;
  }
  .failed {
    max-width: 480px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  code {
    font-family: var(--mono);
    font-size: 12px;
  }
</style>
