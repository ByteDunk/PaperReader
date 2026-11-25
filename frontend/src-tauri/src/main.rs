#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod process;

use process::BackendProcess;
use serde::Serialize;
use std::{
    ffi::OsString,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Condvar, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Connection {
    base_url: String,
    token: String,
}
enum Status {
    Starting,
    Models(serde_json::Value),
    Ready(Connection),
    Failed(String),
}
struct Desktop {
    root: PathBuf,
    status: Mutex<Status>,
    changed: Condvar,
    process: Mutex<Option<BackendProcess>>,
    closing: AtomicBool,
    window_ready: AtomicBool,
}

impl Desktop {
    fn set_status(&self, status: Status) {
        *self.status.lock().unwrap() = status;
        self.changed.notify_all();
    }

    fn connection(&self) -> Result<Connection, String> {
        let mut status = self.status.lock().unwrap();
        loop {
            match &*status {
                Status::Ready(value) => return Ok(value.clone()),
                Status::Failed(error) => return Err(error.clone()),
                // Consent and downloads can take arbitrarily long. Only time
                // out the actual backend startup, including after installation.
                Status::Models(_) => status = self.changed.wait(status).unwrap(),
                Status::Starting => {
                    let (next, timeout) = self
                        .changed
                        .wait_timeout_while(status, Duration::from_secs(120), |s| {
                            matches!(s, Status::Starting)
                        })
                        .unwrap();
                    status = next;
                    if timeout.timed_out() && matches!(*status, Status::Starting) {
                        return Err(format!(
                            "启动超时，请查看 {}",
                            self.root.join("data/logs/backend.log").display()
                        ));
                    }
                }
            }
        }
    }

    fn stop(&self) {
        if self.closing.swap(true, Ordering::SeqCst) {
            return;
        }
        let connection = match &*self.status.lock().unwrap() {
            Status::Ready(c) => Some(c.clone()),
            _ => None,
        };
        if let Some(c) = connection {
            let _ = http(&c, "POST", "/api/desktop/shutdown");
        }
        if let Some(child) = self.process.lock().unwrap().take() {
            child.wait(750);
            drop(child);
        }
        let mut status = self.status.lock().unwrap();
        if matches!(*status, Status::Starting | Status::Models(_)) {
            *status = Status::Failed(format!(
                "应用服务启动超时，请查看 {}",
                self.root.join("data/logs/backend.log").display()
            ));
        }
        self.changed.notify_all();
    }

    fn start(self: &Arc<Self>) {
        let state = self.clone();
        std::thread::spawn(move || {
            if let Err(error) = state.launch() {
                state.set_status(Status::Failed(format!(
                    "{}\n日志：{}",
                    error,
                    state.root.join("data/logs/backend.log").display()
                )));
                if let Some(child) = state.process.lock().unwrap().take() {
                    drop(child);
                }
            }
        });
        let state = self.clone();
        std::thread::spawn(move || {
            if state.connection().is_err() {
                state.stop();
            }
        });
    }

    fn launch(&self) -> Result<(), Box<dyn std::error::Error>> {
        let data = self.root.join("data");
        let log_path = data.join("logs/backend.log");
        if fs::metadata(&log_path)
            .map(|m| m.len() > 5_000_000)
            .unwrap_or(false)
        {
            let _ = fs::rename(&log_path, data.join("logs/backend.previous.log"));
        }
        let mut log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)?;
        let token = format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        );
        let mut args = Vec::<OsString>::new();
        let exe = if cfg!(debug_assertions) {
            args.push(
                self.root
                    .join("packaging/backend_entry.py")
                    .into_os_string(),
            );
            self.root.join("backend/.venv/Scripts/python.exe")
        } else {
            self.root.join("backend/paperreader-backend.exe")
        };
        if !exe.is_file() {
            return Err(format!("找不到应用组件：{}。请完整解压发行包。", exe.display()).into());
        }
        args.extend([
            "--data-dir".into(),
            data.into_os_string(),
            "--models-dir".into(),
            self.root.join("models").into_os_string(),
        ]);
        let env = [
            ("PAPERREADER_SESSION_TOKEN", OsString::from(&token)),
            ("PYTHONUTF8", "1".into()),
            ("PYTHONIOENCODING", "utf-8".into()),
            ("PYTHONUNBUFFERED", "1".into()),
        ];
        let stdout = {
            let mut owner = self.process.lock().unwrap();
            if self.closing.load(Ordering::SeqCst) {
                return Ok(());
            }
            let (child, stdout) = BackendProcess::spawn(&exe, &args, &self.root, &env, &log)?;
            *owner = Some(child);
            stdout
        };
        let mut announced = false;
        for line in BufReader::new(stdout).split(b'\n') {
            let bytes = line?;
            let line = String::from_utf8_lossy(&bytes);
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) {
                if !announced && value["event"] == "paperreader_models" {
                    if value["phase"] == "starting" {
                        // A blocked stdin reader can stall native Python imports on Windows.
                        if let Some(child) = self.process.lock().unwrap().as_mut() {
                            child.finish_model_setup();
                        }
                        self.set_status(Status::Starting);
                    } else {
                        let mut status = self.status.lock().unwrap();
                        let mut value = value;
                        if matches!(&*status, Status::Models(current) if current["phase"] == "pausing")
                            && value["phase"] == "downloading"
                        {
                            value["phase"] = "pausing".into();
                        }
                        *status = Status::Models(value);
                        self.changed.notify_all();
                    }
                    continue;
                }
                if !announced && value["event"] == "paperreader_ready" {
                    let url = value["url"].as_str().ok_or("Invalid startup response")?;
                    let address: SocketAddr = url
                        .strip_prefix("http://")
                        .ok_or("Invalid backend address")?
                        .parse()?;
                    if address.ip() != std::net::Ipv4Addr::LOCALHOST || address.port() == 0 {
                        return Err("Invalid loopback address".into());
                    }
                    let connection = Connection {
                        base_url: url.into(),
                        token: token.clone(),
                    };
                    let deadline = Instant::now() + Duration::from_secs(10);
                    while !http(&connection, "GET", "/api/desktop/health") {
                        if self.closing.load(Ordering::SeqCst) {
                            return Ok(());
                        }
                        if Instant::now() >= deadline {
                            return Err("应用服务未能就绪。".into());
                        }
                        std::thread::sleep(Duration::from_millis(50));
                    }
                    self.set_status(Status::Ready(connection));
                    announced = true;
                    continue;
                }
            }
            writeln!(log, "{line}")?;
        }
        if !self.closing.load(Ordering::SeqCst) {
            return Err("应用服务意外退出，请重新打开应用。".into());
        }
        Ok(())
    }
}

fn http(connection: &Connection, method: &str, path: &str) -> bool {
    let Some(address) = connection
        .base_url
        .strip_prefix("http://")
        .and_then(|v| v.parse::<SocketAddr>().ok())
    else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(150)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(150)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(150)));
    if write!(stream, "{method} {path} HTTP/1.1\r\nHost: {address}\r\nX-PaperReader-Token: {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", connection.token).is_err() { return false; }
    let mut response = [0; 256];
    let Ok(n) = stream.read(&mut response) else {
        return false;
    };
    response[..n].starts_with(b"HTTP/1.1 20")
}

#[tauri::command]
async fn desktop_connection(state: tauri::State<'_, Arc<Desktop>>) -> Result<Connection, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || state.connection())
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
fn desktop_startup_status(state: tauri::State<'_, Arc<Desktop>>) -> serde_json::Value {
    use serde_json::json;
    match &*state.status.lock().unwrap() {
        Status::Starting => json!({ "phase": "starting" }),
        Status::Models(value) => value.clone(),
        Status::Ready(_) => json!({ "phase": "ready" }),
        Status::Failed(error) => json!({ "phase": "error", "error": error }),
    }
}

#[tauri::command]
fn desktop_download_models(state: tauri::State<'_, Arc<Desktop>>, pause: bool) -> Result<(), String> {
    let mut status = state.status.lock().unwrap();
    let allowed: &[&str] = if pause { &["downloading"] } else { &["confirm", "download_error", "paused"] };
    if !matches!(&*status, Status::Models(value)
        if allowed.contains(&value["phase"].as_str().unwrap_or("")))
    {
        return Err("当前不能执行此下载操作。".into());
    }
    state
        .process
        .lock()
        .unwrap()
        .as_mut()
        .ok_or("应用服务未启动。")?
        .download_models(pause)
        .map_err(|error| error.to_string())?;
    if let Status::Models(value) = &mut *status {
        value["phase"] = if pause { "pausing" } else { "downloading" }.into();
        value["error"] = serde_json::Value::Null;
    }
    state.changed.notify_all();
    Ok(())
}

#[tauri::command]
fn desktop_frontend_ready(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Desktop>>,
) -> Result<(), String> {
    if window.label() != "main" {
        return Err("无效的应用窗口。".into());
    }
    if !state.window_ready.load(Ordering::SeqCst) {
        window.show().map_err(|error| error.to_string())?;
        state.window_ready.store(true, Ordering::SeqCst);
        let _ = window.set_focus();
    }
    Ok(())
}

fn app_root() -> Result<PathBuf, Box<dyn std::error::Error>> {
    if cfg!(debug_assertions) {
        Ok(Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()?)
    } else {
        Ok(std::env::current_exe()?
            .parent()
            .ok_or("应用路径无效")?
            .to_path_buf())
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    tauri::webview_version()
        .map_err(|e| format!("无法使用 Windows WebView2，请修复系统 WebView2 Runtime。\n{e}"))?;
    let root = app_root()?;
    for folder in ["config", "library", "webview", "runtime", "logs"] {
        fs::create_dir_all(root.join("data").join(folder))?;
    }
    let probe = root.join("data/.write-test");
    fs::write(&probe, b"")
        .map_err(|_| "无法写入应用数据，请将整个文件夹解压到有写入权限的位置。")?;
    fs::remove_file(probe)?;
    let state = Arc::new(Desktop {
        root,
        status: Mutex::new(Status::Starting),
        changed: Condvar::new(),
        process: Mutex::new(None),
        closing: AtomicBool::new(false),
        window_ready: AtomicBool::new(false),
    });
    let setup_state = state.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            // A second launch must not expose the first instance's empty WebView.
            if !app.state::<Arc<Desktop>>().window_ready.load(Ordering::SeqCst) {
                return;
            }
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .manage(state.clone())
        .invoke_handler(tauri::generate_handler![desktop_connection, desktop_frontend_ready,
                                               desktop_startup_status, desktop_download_models])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("文献阅读器")
                // Let WebView2 deliver HTML5 file and tab drags to Vue.
                .disable_drag_drop_handler()
                .inner_size(1440.0, 920.0)
                .min_inner_size(960.0, 640.0)
                .decorations(false)
                .maximized(true)
                // Vue reveals the window after its startup screen is laid out.
                .visible(false)
                .data_directory(setup_state.root.join("data/webview"))
                .build()?;
            setup_state.start();
            // Missing/broken frontend assets must not leave an invisible process.
            // This is independent of the backend's longer startup timeout.
            let handle = app.handle().clone();
            let startup_state = setup_state.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(30));
                if startup_state.window_ready.load(Ordering::SeqCst) {
                    return;
                }
                let exit_handle = handle.clone();
                let _ = handle.run_on_main_thread(move || {
                    // The backend may already have failed and stopped; the
                    // frontend still needs a visible error in that case.
                    if !startup_state.window_ready.load(Ordering::SeqCst) {
                        process::show_error("应用启动界面未能加载，请关闭后重新打开。若问题持续，请重新完整解压应用。");
                        exit_handle.exit(1);
                    }
                });
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                window.app_handle().exit(0);
            }
        })
        .build(tauri::generate_context!())?;
    app.run(move |_, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            state.stop();
        }
    });
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        process::show_error(&format!("文献阅读器启动失败。\n{error}"));
    }
}
