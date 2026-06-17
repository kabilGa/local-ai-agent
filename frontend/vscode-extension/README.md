# Local AI Agent — VS Code Extension

VS Code extension for the local open-source AI coding / debugging / security agent.
Everything runs on-premise — no cloud APIs, no telemetry.

---

## Features

| Feature | How to use |
|---|---|
| **Chat sidebar** | Click the ⚡ icon in the Activity Bar |
| **Ask about a file** | Right-click any file → *Ask AI Agent About This File* |
| **Ask about selection** | Select code → Right-click → *Ask AI Agent About Selected Code* |
| **Security scan (file)** | Right-click in editor → *Run Security Scan on Current File* |
| **Security scan (workspace)** | Command Palette → *AI Agent: Run Security Scan on Entire Workspace* |
| **Review & apply patch** | When AI proposes a patch, click **Review & Apply** in the chat panel |
| **Keyboard shortcut** | `Ctrl+Shift+A` (Windows/Linux) / `Cmd+Shift+A` (Mac) → Open Chat |

---

## Prerequisites

- VS Code **1.85+**
- Node.js **18+**
- The **API Gateway** running at `http://localhost:8000`
  (or configure a different URL in Settings)

---

## Setup

```bash
# 1. Go into the extension folder
cd frontend/vscode-extension

# 2. Install dependencies
npm install

# 3. Compile the extension
npm run compile
```

### Running in development (no install needed)

1. Open `frontend/vscode-extension/` as a folder in VS Code
2. Press **F5**
3. A new **Extension Development Host** window opens with the extension loaded
4. Make changes → `npm run compile` → Reload the Host window (`Ctrl+R`)

### Packaging as a `.vsix` file

```bash
npm run package
# Produces: local-ai-agent-0.1.0.vsix

# Install in any VS Code:
code --install-extension local-ai-agent-0.1.0.vsix
```

---

## Configuration

Open VS Code Settings (`Ctrl+,`) and search for **"AI Agent"**:

| Setting | Default | Description |
|---|---|---|
| `localAiAgent.apiUrl` | `http://localhost:8000` | URL of the API Gateway |
| `localAiAgent.apiToken` | *(empty)* | JWT token from the web portal login |
| `localAiAgent.explainMode` | `standard` | Response detail: `novice`, `standard`, `expert` |
| `localAiAgent.defaultProject` | *(empty)* | Default project ID for scans |

> **Never commit your API token.** The token field is stored in VS Code's global settings file, which is not part of your repo.

---

## Architecture

```
src/
├── extension.ts              ← activate() — boots everything
├── api/
│   └── agentClient.ts        ← HTTP client for the API Gateway
├── panels/
│   └── ChatPanel.ts          ← Sidebar WebviewView host
├── providers/
│   ├── DiagnosticsProvider.ts ← Security findings → Problems panel
│   └── CodeActionProvider.ts  ← Lightbulb quick-fixes
├── commands/
│   ├── askAboutFile.ts       ← File/selection context commands
│   ├── applyPatch.ts         ← Diff viewer + apply/reject flow
│   └── runSecurityScan.ts    ← SAST/SCA scan commands
└── webview/
    ├── chat.html             ← Sidebar panel HTML (no React needed)
    └── chat.css              ← VS Code theme-aware styles
```

**Key architecture note:** Extension code (Node.js) and the webview HTML (browser-like sandbox) run in separate processes and can **only communicate via `postMessage()`**. The `agentClient.ts` API calls happen on the extension side — never in the webview — because webviews cannot make HTTP requests to `localhost` directly.

---

## Spec compliance

| Requirement | ID | Status |
|---|---|---|
| Conversational interface in IDE | F-01 | ✅ Chat sidebar panel |
| Diff shown before any patch | F-08 | ✅ VS Code native diff editor |
| Reject / rollback patches | F-09 | ✅ Reject button + API call |
| Sourced responses with file links | F-07 | ✅ Source citation buttons |
| Security findings in Problems panel | APPSEC-01/02 | ✅ DiagnosticsProvider |
| OWASP/CWE category mapping | APPSEC-03 | ✅ Shown in diagnostic message |
| Novice / Standard / Expert mode | F-11 | ✅ Toolbar dropdown |
| Human-in-the-loop (no auto-apply) | arch | ✅ Explicit confirmation modal |
| 100% local / no telemetry | §3.3 | ✅ All calls go to localhost |

---

## Common mistakes & fixes

| Problem | Symptom | Fix |
|---|---|---|
| API Gateway not running | "Cannot reach AI Agent" error | Start the backend: `docker-compose up` |
| No token set | 401 errors | Add token in Settings → `localAiAgent.apiToken` |
| Wrong project ID | "Set a default project" warning | Set `localAiAgent.defaultProject` or select from dropdown |
| Webview scripts blocked | Blank panel, no JS errors | Make sure `{{NONCE}}` is being replaced (check ChatPanel.ts logs) |
| Extension not reloading | Old code still running | `Ctrl+R` in the Extension Development Host window |
