/**
 * agentClient.ts
 *
 * Thin HTTP client that talks to the AI Agent API Gateway.
 * Uses Node's built-in `https`/`http` modules — NOT browser fetch —
 * because VS Code extensions run in Node.js, not a browser.
 *
 * All request shapes match openapi.yaml exactly (same contract as the web portal).
 */

import * as http from 'http'
import * as https from 'https'
import * as vscode from 'vscode'

// ─── Types (mirror openapi.yaml schemas) ─────────────────────────────────────

export interface ChatRequest {
  message: string
  project: string
  explainMode?: 'novice' | 'standard' | 'expert'
  conversationId?: string
}

export interface SourceCitation {
  file: string
  lineStart: number
  lineEnd: number
  snippet: string
}

export interface PatchProposal {
  id: string
  title: string
  explanation: string
  diff: string
  status: 'pending' | 'applied' | 'rejected'
}

export interface ChatResponse {
  response: string
  conversationId: string
  sources?: SourceCitation[]
  patch?: PatchProposal
}

export interface Project {
  id: string
  name: string
  repo: string
  branch: string
}

export interface SecurityFinding {
  file: string
  line: number
  endLine?: number
  severity: 'error' | 'warning' | 'info'
  message: string
  ruleId: string
  category: string // e.g. "OWASP-A03", "CWE-79"
}

export interface SecurityScanResponse {
  findings: SecurityFinding[]
  summary: string
  scannedFiles: number
}

// ─── Config helpers ───────────────────────────────────────────────────────────

function getConfig() {
  const cfg = vscode.workspace.getConfiguration('localAiAgent')
  return {
    apiUrl: (cfg.get<string>('apiUrl') || 'http://localhost:8000').replace(/\/$/, ''),
    token: cfg.get<string>('apiToken') || '',
    explainMode: cfg.get<'novice' | 'standard' | 'expert'>('explainMode') || 'standard',
    defaultProject: cfg.get<string>('defaultProject') || '',
  }
}

// ─── Core request function ────────────────────────────────────────────────────

/**
 * Makes an HTTP/HTTPS request to the API Gateway.
 * Returns parsed JSON or throws a descriptive Error.
 */
function request<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: unknown
): Promise<T> {
  return new Promise((resolve, reject) => {
    const { apiUrl, token } = getConfig()
    const url = new URL(apiUrl + path)
    const isHttps = url.protocol === 'https:'
    const lib = isHttps ? https : http

    const payload = body ? JSON.stringify(body) : undefined

    const options: http.RequestOptions = {
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
      },
    }

    const req = lib.request(options, (res) => {
      let data = ''
      res.on('data', chunk => { data += chunk })
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data) as T
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`API error ${res.statusCode}: ${data}`))
          } else {
            resolve(parsed)
          }
        } catch {
          reject(new Error(`Failed to parse API response: ${data}`))
        }
      })
    })

    req.on('error', (err) => {
      if ((err as NodeJS.ErrnoException).code === 'ECONNREFUSED') {
        reject(new Error(
          `Cannot reach AI Agent at ${apiUrl}. Is the API Gateway running?\n` +
          `Check: Settings > localAiAgent.apiUrl`
        ))
      } else {
        reject(err)
      }
    })

    if (payload) req.write(payload)
    req.end()
  })
}

// ─── Public API ───────────────────────────────────────────────────────────────

/** Send a chat message and get an AI response. */
export async function sendChatMessage(req: ChatRequest): Promise<ChatResponse> {
  const { explainMode } = getConfig()
  return request<ChatResponse>('POST', '/api/chat', {
    explainMode,
    ...req,
  })
}

/** List available projects/repos. */
export async function listProjects(): Promise<Project[]> {
  return request<Project[]>('GET', '/api/projects')
}

/** Get a specific patch proposal by ID. */
export async function getPatch(id: string): Promise<PatchProposal> {
  return request<PatchProposal>('GET', `/api/patches/${id}`)
}

/** Apply a patch (requires prior user confirmation — never call silently). */
export async function applyPatch(id: string): Promise<PatchProposal> {
  return request<PatchProposal>('POST', `/api/patches/${id}/apply`)
}

/** Reject a patch. */
export async function rejectPatch(id: string): Promise<PatchProposal> {
  return request<PatchProposal>('POST', `/api/patches/${id}/reject`)
}

/**
 * Request a security scan for a specific file path.
 * The API Gateway will route this to the SAST/SCA tools in the sandbox.
 */
export async function runSecurityScan(
  filePath: string,
  projectId: string
): Promise<SecurityScanResponse> {
  return request<SecurityScanResponse>('POST', '/api/security/scan', {
    file: filePath,
    project: projectId,
  })
}

/**
 * Request a workspace-wide security scan.
 */
export async function runWorkspaceScan(projectId: string): Promise<SecurityScanResponse> {
  return request<SecurityScanResponse>('POST', '/api/security/scan', {
    project: projectId,
    scope: 'workspace',
  })
}

/** Helper: get the configured default project ID (may be empty string). */
export function getDefaultProject(): string {
  return getConfig().defaultProject
}

/** Helper: get the current explain mode from settings. */
export function getExplainMode(): 'novice' | 'standard' | 'expert' {
  return getConfig().explainMode
}
