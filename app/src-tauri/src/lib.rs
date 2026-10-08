//! Sidecar desktop shell: owns the window and the Python engine process.

use std::fs::File;
use std::io::Read;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, Url, WebviewUrl, WebviewWindowBuilder};

/// Connection details for the engine, and its process handle.
struct Engine {
    port: u16,
    token: String,
    child: Mutex<Option<Child>>,
    error: Mutex<Option<String>>,
}

#[derive(Serialize)]
struct EngineInfo {
    port: u16,
    token: String,
    error: Option<String>,
}

/// Returns the port and token the UI uses to reach the engine.
#[tauri::command]
fn engine_info(engine: State<Engine>) -> EngineInfo {
    EngineInfo {
        port: engine.port,
        token: engine.token.clone(),
        error: engine.error.lock().unwrap().clone(),
    }
}

/// True while a call is recording, so quitting can be refused.
#[derive(Default)]
struct CallState {
    active: AtomicBool,
}

#[tauri::command]
fn set_call_active(active: bool, call: State<CallState>) {
    call.active.store(active, Ordering::SeqCst);
}

/// Opens the live call window, or focuses it if it is already open.
/// Only the coach's local address is allowed.
#[tauri::command]
fn open_call_window(app: AppHandle, url: String, title: String) -> Result<(), String> {
    let url = Url::parse(&url).map_err(|e| e.to_string())?;
    if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") {
        return Err("The call window only opens the local coach".into());
    }
    if let Some(window) = app.get_webview_window("call") {
        if window.url().map_err(|e| e.to_string())? != url {
            window.navigate(url).map_err(|e| e.to_string())?;
        }
        window.set_title(&title).map_err(|e| e.to_string())?;
        window.show().map_err(|e| e.to_string())?;
        return window.set_focus().map_err(|e| e.to_string());
    }
    WebviewWindowBuilder::new(&app, "call", WebviewUrl::External(url))
        .title(title)
        .inner_size(1180.0, 820.0)
        .min_inner_size(720.0, 520.0)
        .theme(Some(tauri::Theme::Dark))
        .build()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

fn random_token() -> std::io::Result<String> {
    let mut bytes = [0u8; 24];
    File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

/// Finds `uv` for development runs. Apps started from Finder lack the shell PATH.
fn find_uv() -> PathBuf {
    if let Ok(path) = std::env::var("SIDECAR_UV") {
        return PathBuf::from(path);
    }
    for candidate in ["/opt/homebrew/bin/uv", "/usr/local/bin/uv"] {
        let path = PathBuf::from(candidate);
        if path.exists() {
            return path;
        }
    }
    PathBuf::from("uv")
}

/// Builds the engine command: the bundled binary when present, else `uv run` in the repo.
fn engine_command(port: u16, token: &str) -> std::io::Result<Command> {
    let exe_dir = std::env::current_exe()?
        .parent()
        .map(PathBuf::from)
        .unwrap_or_default();
    let bundled = exe_dir.join("sidecar-engine");
    let mut cmd = if bundled.exists() {
        Command::new(bundled)
    } else {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mut c = Command::new(find_uv());
        c.current_dir(repo)
            .args(["run", "--quiet", "sidecar-engine"]);
        c
    };
    cmd.args(["--port", &port.to_string(), "--watch-stdin"])
        .env("SIDECAR_TOKEN", token)
        .stdin(Stdio::piped());
    Ok(cmd)
}

fn start_engine() -> Engine {
    let port = free_port().unwrap_or(0);
    let token = random_token().unwrap_or_default();
    let mut error = None;
    let child = match engine_command(port, &token).and_then(|mut c| c.spawn()) {
        Ok(child) => Some(child),
        Err(err) => {
            error = Some(format!("Could not start the engine: {err}"));
            None
        }
    };
    if port == 0 || token.is_empty() {
        error = Some("Could not pick a port or token for the engine".into());
    }
    Engine {
        port,
        token,
        child: Mutex::new(child),
        error: Mutex::new(error),
    }
}

fn stop_engine(engine: &Engine) {
    if let Some(mut child) = engine.child.lock().unwrap().take() {
        drop(child.stdin.take());
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(start_engine())
        .manage(CallState::default())
        .invoke_handler(tauri::generate_handler![
            engine_info,
            open_call_window,
            set_call_active
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Sidecar app");

    app.run(|handle, event| match event {
        RunEvent::ExitRequested { api, .. } => {
            if handle.state::<CallState>().active.load(Ordering::SeqCst) {
                api.prevent_exit();
                let _ = handle.emit("quit-blocked", ());
                if let Some(window) = handle.get_webview_window("call") {
                    let _ = window.set_focus();
                }
            }
        }
        RunEvent::Exit => stop_engine(&handle.state::<Engine>()),
        _ => {}
    });
}
