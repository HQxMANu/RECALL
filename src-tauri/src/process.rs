use std::{
    fs,
    fs::File,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    thread,
};

use anyhow::{anyhow, Context};
use log::{error, info};
use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Manager};
use zip::ZipArchive;

use crate::models::{WorkerRequest, WorkerResponse};

#[derive(Clone)]
pub struct WorkerClient {
    inner: Arc<WorkerClientInner>,
}

struct WorkerClientInner {
    io: Mutex<WorkerIo>,
    request_id: AtomicU64,
    _child_guard: Mutex<Child>,
}

struct WorkerIo {
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl WorkerClient {
    pub fn new(worker_root: &Path, app_data_dir: &Path) -> anyhow::Result<Self> {
        let python = resolve_python_executable(worker_root);
        let worker_script = worker_root.join("python").join("run_worker.py");

        if !worker_script.exists() {
            return Err(anyhow!(
                "Python worker script not found at {}",
                worker_script.display()
            ));
        }

        let mut command = Command::new(&python);
        command
            .arg(&worker_script)
            .current_dir(worker_root)
            .env("PYTHONUTF8", "1")
            .env("RECALL_APP_DATA_DIR", app_data_dir)
            .env("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .env("USE_TF", "0")
            .env("TRANSFORMERS_NO_TF", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        info!(
            "Starting Recall worker from {} with Python {}",
            worker_script.display(),
            python
        );

        let mut child = command
            .spawn()
            .with_context(|| format!("Failed to start Python worker with {}", python))?;

        let stderr = child
            .stderr
            .take()
            .context("Failed to capture Python worker stderr")?;
        let stdin = child
            .stdin
            .take()
            .context("Failed to capture Python worker stdin")?;
        let stdout = child
            .stdout
            .take()
            .context("Failed to capture Python worker stdout")?;

        thread::Builder::new()
            .name("recall-worker-stderr".to_string())
            .spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines().map_while(Result::ok) {
                    info!(target: "recall_worker", "{line}");
                }
            })
            .context("Failed to spawn stderr log thread")?;

        Ok(Self {
            inner: Arc::new(WorkerClientInner {
                io: Mutex::new(WorkerIo {
                    stdin,
                    stdout: BufReader::new(stdout),
                }),
                request_id: AtomicU64::new(1),
                _child_guard: Mutex::new(child),
            }),
        })
    }

    pub fn terminate(&self) {
        if let Ok(mut child) = self.inner._child_guard.lock() {
            let _ = child.kill();
        }
    }

    pub async fn request<P, R>(&self, method: &str, params: P) -> Result<R, String>
    where
        P: Serialize + Send + 'static,
        R: DeserializeOwned + Send + 'static,
    {
        let method = method.to_string();
        let inner = self.inner.clone();
        let value = serde_json::to_value(params).map_err(|error| error.to_string())?;

        tauri::async_runtime::spawn_blocking(move || {
            inner
                .request_sync(&method, value)
                .map_err(|error| error.to_string())
        })
        .await
        .map_err(|error| error.to_string())?
    }

    pub async fn ping(&self) -> Result<(), String> {
        let _: Value = self.request("get_health", json!({})).await?;
        Ok(())
    }
}

impl WorkerClientInner {
    fn request_sync<R: DeserializeOwned>(&self, method: &str, params: Value) -> anyhow::Result<R> {
        let request_id = self.request_id.fetch_add(1, Ordering::Relaxed);
        let request = WorkerRequest {
            id: request_id,
            method: method.to_string(),
            params,
        };

        let mut io = self
            .io
            .lock()
            .map_err(|_| anyhow!("Failed to lock Python worker IO"))?;

        let payload = serde_json::to_string(&request)?;
        writeln!(io.stdin, "{payload}")?;
        io.stdin.flush()?;

        let mut line = String::new();
        io.stdout.read_line(&mut line)?;

        if line.trim().is_empty() {
            return Err(anyhow!("Python worker closed the response stream"));
        }

        let response: WorkerResponse = serde_json::from_str(&line)
            .with_context(|| format!("Invalid worker response: {}", line.trim()))?;

        if response.id != request_id {
            return Err(anyhow!(
                "Mismatched worker response id {} for request {}",
                response.id,
                request_id
            ));
        }

        if let Some(error) = response.error {
            error!(target: "recall_worker", "Worker method {method} failed: {error}");
            return Err(anyhow!(error));
        }

        let result = response
            .result
            .ok_or_else(|| anyhow!("Worker returned no result for method {method}"))?;

        Ok(serde_json::from_value(result)?)
    }
}

pub fn worker_root(app: &AppHandle, app_data_dir: &Path) -> anyhow::Result<PathBuf> {
    if let Some(root) = resolve_dev_worker_root()? {
        return Ok(root);
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .context("Unable to resolve Tauri resource directory")?;

    if resource_dir.join("python").join("run_worker.py").exists() {
        return Ok(resource_dir);
    }

    let bundled_archive = resource_dir.join("worker-runtime.zip");
    if bundled_archive.exists() {
        return prepare_bundled_worker_root(&bundled_archive, app_data_dir);
    }

    if let Some(executable_dir) = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf))
    {
        if executable_dir.join("python").join("run_worker.py").exists() {
            return Ok(executable_dir);
        }
    }

    let current = std::env::current_dir().context("Unable to locate current project directory")?;
    if current.join("python").join("run_worker.py").exists() {
        return Ok(current);
    }

    Err(anyhow!(
        "Unable to locate bundled Recall worker resources from {} or {}",
        current.display(),
        resource_dir.display()
    ))
}

pub fn resolve_python_executable(worker_root: &Path) -> String {
    if let Ok(configured) = std::env::var("RECALL_PYTHON_EXE") {
        if !configured.trim().is_empty() {
            return configured;
        }
    }

    let project_venv = worker_root
        .join("python")
        .join(".venv")
        .join("Scripts")
        .join("python.exe");
    if project_venv.exists() {
        return project_venv.to_string_lossy().to_string();
    }

    "python".to_string()
}

fn prepare_bundled_worker_root(archive_path: &Path, app_data_dir: &Path) -> anyhow::Result<PathBuf> {
    let runtime_root = app_data_dir.join("worker-runtime");
    let stamp_path = runtime_root.join(".bundle-stamp");
    let stamp = archive_stamp(archive_path)?;
    let needs_refresh = !runtime_root.join("python").join("run_worker.py").exists()
        || fs::read_to_string(&stamp_path).ok().as_deref() != Some(&stamp);

    if needs_refresh {
        if runtime_root.exists() {
            fs::remove_dir_all(&runtime_root)
                .with_context(|| format!("Failed to clear {}", runtime_root.display()))?;
        }
        fs::create_dir_all(&runtime_root)
            .with_context(|| format!("Failed to create {}", runtime_root.display()))?;
        extract_archive(archive_path, &runtime_root)?;
        fs::write(&stamp_path, stamp)
            .with_context(|| format!("Failed to write {}", stamp_path.display()))?;
    }

    Ok(runtime_root)
}

fn resolve_dev_worker_root() -> anyhow::Result<Option<PathBuf>> {
    if let Ok(configured) = std::env::var("RECALL_PYTHON_EXE") {
        if !configured.trim().is_empty() {
            let configured_path = PathBuf::from(configured);
            if let Some(root) = configured_path
                .ancestors()
                .find(|candidate| candidate.join("python").join("run_worker.py").exists())
            {
                return Ok(Some(root.to_path_buf()));
            }
        }
    }

    let current = std::env::current_dir().context("Unable to locate current project directory")?;
    if current
        .file_name()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case("src-tauri"))
    {
        if let Some(root) = current.parent() {
            if root.join("python").join("run_worker.py").exists() {
                return Ok(Some(root.to_path_buf()));
            }
        }
    }

    if let Some(root) = current
        .ancestors()
        .find(|candidate| candidate.join("python").join("run_worker.py").exists())
    {
        return Ok(Some(root.to_path_buf()));
    }

    Ok(None)
}

fn archive_stamp(archive_path: &Path) -> anyhow::Result<String> {
    let metadata = fs::metadata(archive_path)
        .with_context(|| format!("Failed to read {}", archive_path.display()))?;
    let modified = metadata
        .modified()
        .context("Failed to read worker archive modified time")?
        .duration_since(std::time::UNIX_EPOCH)
        .context("Worker archive modified time predates UNIX_EPOCH")?
        .as_secs();
    Ok(format!("{}:{modified}", metadata.len()))
}

fn extract_archive(archive_path: &Path, target_dir: &Path) -> anyhow::Result<()> {
    let file = File::open(archive_path)
        .with_context(|| format!("Failed to open {}", archive_path.display()))?;
    let mut archive = ZipArchive::new(file).context("Failed to read worker runtime archive")?;

    for index in 0..archive.len() {
        let mut entry = archive.by_index(index).context("Failed to read runtime bundle entry")?;
        let enclosed = entry
            .enclosed_name()
            .ok_or_else(|| anyhow!("Runtime bundle contained an invalid path"))?
            .to_path_buf();
        let destination = target_dir.join(enclosed);

        if entry.is_dir() {
            fs::create_dir_all(&destination)
                .with_context(|| format!("Failed to create {}", destination.display()))?;
            continue;
        }

        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("Failed to create {}", parent.display()))?;
        }

        let mut output = File::create(&destination)
            .with_context(|| format!("Failed to create {}", destination.display()))?;
        std::io::copy(&mut entry, &mut output)
            .with_context(|| format!("Failed to extract {}", destination.display()))?;
    }

    Ok(())
}
