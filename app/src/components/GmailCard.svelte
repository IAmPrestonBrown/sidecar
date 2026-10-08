<script lang="ts">
  import { gmail } from '../lib/gmail.svelte'
  import GoogleButton from './GoogleButton.svelte'

  let { reason = '' }: { reason?: string } = $props()
  let confirming = $state(false)

  $effect(() => {
    if (!gmail.status) gmail.refresh()
  })

  const status = $derived(gmail.status)
  const initial = $derived(status?.email.charAt(0).toUpperCase() ?? '')
</script>

<section class="card group" aria-label="Gmail account">
  {#if !status}
    <span class="muted">Checking Gmail…</span>
  {:else if status.connected}
    <div class="row">
      <span class="avatar" aria-hidden="true">{initial}</span>
      <span class="stack">
        <span class="strong selectable">{status.email}</span>
        <span class="muted">Gmail connected. Sends approved email and reads replies in its threads.</span>
      </span>
      <span class="spacer"></span>
      {#if confirming}
        <button class="btn small" onclick={() => (confirming = false)}>Cancel</button>
        <button
          class="btn small danger"
          onclick={async () => {
            await gmail.disconnect()
            confirming = false
          }}>Disconnect</button
        >
      {:else}
        <button class="btn small" onclick={() => (confirming = true)}>Disconnect…</button>
      {/if}
    </div>
  {:else if !status.configured}
    <span class="strong">Connect Gmail</span>
    <p class="muted">
      Sidecar sends through your own Google Cloud OAuth client. Create a Desktop app client with the Gmail API
      enabled, download its JSON file, and save it as
      <code class="selectable">{status.client_file}</code>.
    </p>
    <div><button class="btn small" onclick={() => gmail.refresh()}>Check again</button></div>
  {:else}
    <span class="strong">Connect Gmail</span>
    <p class="muted">
      {reason || 'Send approved email from your Google account and see replies here.'} Sidecar asks to send email
      and to read replies to the threads it sends.
    </p>
    <div class="row">
      <GoogleButton
        label={status.connecting ? 'Waiting for your browser…' : 'Sign in with Google'}
        disabled={status.connecting}
        onclick={() => gmail.connect()}
      />
      {#if status.connecting}<span class="muted">Finish signing in in the browser window.</span>{/if}
    </div>
  {/if}
  {#if gmail.error}<p class="contradicts selectable">{gmail.error}</p>{/if}
</section>

<style>
  .card {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .spacer {
    flex: 1 1 auto;
  }
  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--accent-tint);
    color: var(--accent);
    font-weight: 600;
    flex: none;
  }
  code {
    font-family: var(--mono);
    font-size: 12px;
  }
  p {
    margin: 0;
    line-height: 1.45;
  }
</style>
