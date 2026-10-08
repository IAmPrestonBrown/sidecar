<script lang="ts">
  import '@fontsource/roboto/latin-500.css'

  // Follows Google's sign-in branding guidelines: the standard four-color "G",
  // Roboto Medium 14/20, and the light and dark fills and strokes they specify.
  let {
    label = 'Sign in with Google',
    disabled = false,
    onclick,
  }: { label?: string; disabled?: boolean; onclick: () => void } = $props()
</script>

<button class="gsi" type="button" {disabled} {onclick}>
  <svg class="logo" viewBox="0 0 48 48" aria-hidden="true">
    <path
      fill="#EA4335"
      d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
    />
    <path
      fill="#4285F4"
      d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
    />
    <path
      fill="#FBBC05"
      d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
    />
    <path
      fill="#34A853"
      d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
    />
  </svg>
  <span>{label}</span>
</button>

<style>
  .gsi {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    height: 40px;
    padding: 0 12px;
    border: 1px solid #747775;
    border-radius: 20px;
    background: #ffffff;
    color: #1f1f1f;
    font-family: 'Roboto', arial, sans-serif;
    font-size: 14px;
    font-weight: 500;
    line-height: 20px;
    letter-spacing: 0.25px;
    white-space: nowrap;
    cursor: pointer;
    transition: background-color 0.2s;
  }
  .gsi:hover:not(:disabled) {
    background: #f8f9fa;
    box-shadow:
      0 1px 2px 0 rgba(60, 64, 67, 0.3),
      0 1px 3px 1px rgba(60, 64, 67, 0.15);
  }
  .gsi:active:not(:disabled) {
    background: #ececec;
  }
  .gsi:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .gsi:disabled {
    cursor: default;
    background: rgba(255, 255, 255, 0.38);
    border-color: rgba(31, 31, 31, 0.12);
    color: rgba(31, 31, 31, 0.38);
  }
  .gsi:disabled .logo {
    opacity: 0.38;
  }
  .logo {
    width: 20px;
    height: 20px;
    flex: none;
  }
  @media (prefers-color-scheme: dark) {
    .gsi {
      background: #131314;
      border-color: #8e918f;
      color: #e3e3e3;
    }
    .gsi:hover:not(:disabled) {
      background: #1c1c1e;
    }
    .gsi:active:not(:disabled) {
      background: #232325;
    }
    .gsi:disabled {
      background: rgba(19, 19, 20, 0.38);
      border-color: rgba(142, 145, 143, 0.12);
      color: rgba(227, 227, 227, 0.38);
    }
  }
</style>
