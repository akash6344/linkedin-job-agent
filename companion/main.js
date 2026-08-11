const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const crypto = require("crypto");

const STATE_DIR = path.join(os.homedir(), ".letitapply-companion");
const STATE_FILE = path.join(STATE_DIR, "ui-state.json");

function loadUiState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return {};
  }
}

function saveUiState(data) {
  fs.mkdirSync(STATE_DIR, { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(data, null, 2));
}

function deviceId() {
  const st = loadUiState();
  if (st.device_id) return st.device_id;
  const id = crypto.randomBytes(8).toString("hex");
  saveUiState({ ...st, device_id: id });
  return id;
}

function pythonBin() {
  return process.env.LETITAPPLY_PYTHON || "python3";
}

function repoRoot() {
  // companion/ lives at repo root
  return path.resolve(__dirname, "..");
}

function runAgent(args, { timeoutMs = 15 * 60 * 1000 } = {}) {
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      PYTHONPATH: path.join(repoRoot(), "src"),
      LETITAPPLY_API: process.env.LETITAPPLY_API || "http://127.0.0.1:8000",
      LETITAPPLY_COMPANION_DIR: STATE_DIR,
    };
    const child = spawn(pythonBin(), ["-m", "jobsearch_saas.companion_agent", ...args], {
      cwd: repoRoot(),
      env,
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      resolve({ ok: false, error: "Timed out", stdout, stderr });
    }, timeoutMs);
    child.stdout.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr.on("data", (d) => {
      stderr += d.toString();
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      let parsed = null;
      const lines = stdout.trim().split("\n").filter(Boolean);
      const last = lines[lines.length - 1] || "";
      try {
        parsed = JSON.parse(last);
      } catch {
        parsed = null;
      }
      if (parsed) {
        resolve({ ...parsed, exitCode: code, stderr });
        return;
      }
      resolve({
        ok: code === 0,
        error: stderr || stdout || `Exit ${code}`,
        exitCode: code,
        stdout,
        stderr,
      });
    });
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 440,
    height: 640,
    resizable: false,
    title: "LetItApply Companion",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, "index.html"));
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

ipcMain.handle("get-state", async () => {
  const st = loadUiState();
  return {
    email: st.email || "",
    signedIn: Boolean(st.signedIn),
    linkedinConnected: Boolean(st.linkedinConnected),
    lastMessage: st.lastMessage || "",
    deviceId: deviceId(),
    apiBase: process.env.LETITAPPLY_API || "http://127.0.0.1:8000",
  };
});

ipcMain.handle("login", async (_e, { email, password }) => {
  const result = await runAgent([
    "login",
    "--email",
    email,
    "--password",
    password,
    "--device-id",
    deviceId(),
    "--device-name",
    "LetItApply Companion",
  ]);
  if (result.ok !== false && !result.error) {
    saveUiState({
      ...loadUiState(),
      email,
      signedIn: true,
      lastMessage: `Signed in as ${email}`,
    });
    return { ok: true, ...result };
  }
  // companion_agent prints ok:true on success
  if (result.ok) {
    saveUiState({
      ...loadUiState(),
      email,
      signedIn: true,
      lastMessage: `Signed in · plan ${result.plan || ""}`,
    });
  }
  return result;
});

ipcMain.handle("connect-linkedin", async () => {
  const result = await runAgent(["connect-linkedin"], { timeoutMs: 10 * 60 * 1000 });
  if (result.ok) {
    saveUiState({
      ...loadUiState(),
      linkedinConnected: true,
      lastMessage: "LinkedIn connected on this laptop",
    });
  }
  return result;
});

ipcMain.handle("search", async () => {
  const result = await runAgent(["search"], { timeoutMs: 20 * 60 * 1000 });
  if (result.ok) {
    const msg = `Synced ${result.accepted || 0} posts` +
      (result.companion_uploads_remaining != null
        ? ` · ${result.companion_uploads_remaining} uploads left this week`
        : "");
    saveUiState({ ...loadUiState(), lastMessage: msg });
  }
  return result;
});

ipcMain.handle("open-dashboard", async () => {
  const api = process.env.LETITAPPLY_API || "http://127.0.0.1:8000";
  await shell.openExternal(`${api}/dashboard`);
  return { ok: true };
});

ipcMain.handle("open-download-help", async () => {
  const api = process.env.LETITAPPLY_API || "http://127.0.0.1:8000";
  await shell.openExternal(`${api}/download`);
  return { ok: true };
});
