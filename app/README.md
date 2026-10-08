# Sidecar desktop app

The macOS app: a Tauri 2 shell (`src-tauri/`) around a Svelte 5 UI (`src/`).

```sh
npm install
npm run tauri dev       # run the app; Vite serves the UI on 127.0.0.1:1420
npm run check           # svelte-check and TypeScript
npm run lint            # ESLint and Prettier
npm run format          # apply Prettier
npm run tauri build     # build Sidecar.app
```

At launch the Rust shell picks a free port and a random token, starts the Python
engine (`uv run sidecar-engine` from the repository root during development), and
returns both to the UI through the `engine_info` command. All UI requests go to
`http://127.0.0.1:<port>` with the `X-Sidecar-Token` header. The engine exits when
the app quits or its stdin closes.

To work on the UI in a browser, run the engine yourself and point Vite at it:

```sh
SIDECAR_TOKEN=dev-token-0123456789 uv run sidecar-engine --port 8770
VITE_ENGINE_URL=http://127.0.0.1:8770 VITE_ENGINE_TOKEN=dev-token-0123456789 npm run dev
```

The app icon source is `design/icon.png` (1024 px, artwork on the macOS 824 px
grid with transparent corners). Regenerate the bundle icons with
`npm run tauri icon design/icon.png`, then delete the Android, iOS, and Windows
Store variants it also writes.
