/**
 * ChatPanel.ts
 *
 * Manages the AI Agent chat sidebar panel (WebviewView).
 *
 * A WebviewView is an iframe that VS Code embeds in its sidebar.
 * Extension code (Node.js) and webview code (browser JS in chat.html)
 * communicate through a message-passing API — they CANNOT share memory.
 *
 *   Extension side ──postMessage()──▶ Webview (chat.html)
 *   Webview ──────postMessage()──────▶ Extension side (onDidReceiveMessage)
 *
 * Spec requirements fulfilled:
 *  - F-01: Conversational interface in the IDE
 *  - F-07: Source citations displayed with clickable file links
 *  - F-08: Patch proposals trigger the diff viewer (applyPatch.ts)
 *  - F-10: AI response includes uncertainty / confidence signals
 *  - F-11: Explain mode switcher (novice / standard / expert)
 *  - F-12: Conversation history with clear option
 */

import * as vscode from 'vscode'
import * as path from 'path'
import * as fs from 'fs'
import * as agentClient from '../api/agentClient'
import { showAndApplyPatch } from '../commands/applyPatch'

// Messages the webview can send to the extension
type WebviewToExtMessage =
  | { type: 'sendMessage'; text: string; project: string; conversationId?: string }
  | { type: 'applyPatch'; patchId: string }
  | { type: 'rejectPatch'; patchId: string }
  | { type: 'openFile'; file: string; line: number }
  | { type: 'clearHistory' }
  | { type: 'changeExplainMode'; mode: 'novice' | 'standard' | 'expert' }
  | { type: 'ready' }
  | { type: 'listProjects' }

export class ChatPanel implements vscode.WebviewViewProvider {
  public static readonly viewId = 'localAiAgent.chatView'

  private _view?: vscode.WebviewView
  private _extensionUri: vscode.Uri
  private _currentConversationId?: string

  constructor(extensionUri: vscode.Uri) {
    this._extensionUri = extensionUri
  }

  // ── VS Code calls this when it first renders the sidebar view ──────────────
  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView

    webviewView.webview.options = {
      enableScripts: true,
      // Allow loading resources from media/ (webview assets) only
      localResourceRoots: [
        vscode.Uri.joinPath(this._extensionUri, 'media'),
      ],
    }

    webviewView.webview.html = this._getHtmlContent(webviewView.webview)

    // Listen for messages from the webview (chat.html)
    webviewView.webview.onDidReceiveMessage(async (msg: WebviewToExtMessage) => {
      await this._handleWebviewMessage(msg)
    })
  }

  // ── Public: called by commands to focus the panel ─────────────────────────
  public async show(): Promise<void> {
    if (this._view) {
      this._view.show(true) // true = preserve focus in editor
    } else {
      // Panel hasn't been rendered yet — reveal the sidebar
      await vscode.commands.executeCommand('localAiAgent.chatView.focus')
    }
  }

  // ── Public: pre-fill the chat input and auto-send ─────────────────────────
  public sendPrefilled(text: string): void {
    if (!this._view) return
    this._view.webview.postMessage({ type: 'prefill', text })
  }

  // ── Handle messages from the webview ──────────────────────────────────────
  private async _handleWebviewMessage(msg: WebviewToExtMessage): Promise<void> {
    switch (msg.type) {

      case 'ready': {
        // Webview finished loading — send initial config
        const cfg = vscode.workspace.getConfiguration('localAiAgent')
        const defaultProject = cfg.get<string>('defaultProject') || ''
        this._view?.webview.postMessage({
          type: 'config',
          explainMode: cfg.get('explainMode') || 'standard',
          apiUrl: cfg.get('apiUrl') || 'http://localhost:8000',
          defaultProject,
        })
        // Fetch the project list; fall back gracefully if API is not yet running
        try {
          const projects = await agentClient.listProjects()
          this._view?.webview.postMessage({ type: 'projects', projects })
        } catch {
          // API not running — send a fallback so the user can still type and send
          this._view?.webview.postMessage({
            type: 'projects',
            projects: defaultProject
              ? [{ id: defaultProject, name: defaultProject, repo: '', branch: '' }]
              : [{ id: 'default', name: 'Default (offline)', repo: '', branch: '' }],
            offline: true,
          })
        }
        break
      }

      case 'listProjects': {
        try {
          const projects = await agentClient.listProjects()
          this._view?.webview.postMessage({ type: 'projects', projects })
        } catch (err) {
          // Silently fall back — don't show an error for this background refresh
          const defaultProject = agentClient.getDefaultProject()
          this._view?.webview.postMessage({
            type: 'projects',
            projects: defaultProject
              ? [{ id: defaultProject, name: defaultProject, repo: '', branch: '' }]
              : [{ id: 'default', name: 'Default (offline)', repo: '', branch: '' }],
            offline: true,
          })
        }
        break
      }

      case 'sendMessage': {
        // Show a typing indicator in the webview immediately
        this._view?.webview.postMessage({ type: 'typing', value: true })

        try {
          const response = await agentClient.sendChatMessage({
            message: msg.text,
            project: msg.project,
            conversationId: msg.conversationId || this._currentConversationId,
          })

          // Remember conversation ID for follow-up messages
          this._currentConversationId = response.conversationId

          // Send the full response back to the webview for rendering
          this._view?.webview.postMessage({
            type: 'response',
            text: response.response,
            conversationId: response.conversationId,
            sources: response.sources || [],
            patch: response.patch || null,
          })
        } catch (err) {
          this._view?.webview.postMessage({
            type: 'error',
            message: (err as Error).message,
          })
        } finally {
          this._view?.webview.postMessage({ type: 'typing', value: false })
        }
        break
      }

      case 'applyPatch': {
        await showAndApplyPatch(msg.patchId)
        break
      }

      case 'rejectPatch': {
        try {
          await agentClient.rejectPatch(msg.patchId)
          this._view?.webview.postMessage({
            type: 'patchRejected',
            patchId: msg.patchId,
          })
          vscode.window.showInformationMessage('AI Agent: Patch rejected.')
        } catch (err) {
          vscode.window.showErrorMessage(`AI Agent: ${(err as Error).message}`)
        }
        break
      }

      case 'openFile': {
        // Source citation clicked — jump to the file at that line
        try {
          const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri
          if (!workspaceRoot) return
          const fileUri = vscode.Uri.joinPath(workspaceRoot, msg.file)
          const doc = await vscode.workspace.openTextDocument(fileUri)
          const line = Math.max(0, msg.line - 1) // convert to 0-indexed
          const selection = new vscode.Selection(line, 0, line, 0)
          await vscode.window.showTextDocument(doc, { selection, preview: false })
        } catch {
          vscode.window.showWarningMessage(`AI Agent: Could not open file ${msg.file}`)
        }
        break
      }

      case 'clearHistory': {
        this._currentConversationId = undefined
        this._view?.webview.postMessage({ type: 'historyCleared' })
        break
      }

      case 'changeExplainMode': {
        // Persist the user's choice to VS Code settings
        await vscode.workspace
          .getConfiguration('localAiAgent')
          .update('explainMode', msg.mode, vscode.ConfigurationTarget.Global)
        break
      }
    }
  }

  // ── Build the HTML content for the webview ────────────────────────────────
  private _getHtmlContent(webview: vscode.Webview): string {
    // Load HTML from media/chat.html — this folder IS included in the .vsix package
    const htmlPath = path.join(this._extensionUri.fsPath, 'media', 'chat.html')
    const cssPath = path.join(this._extensionUri.fsPath, 'media', 'chat.css')

    let html: string
    try {
      html = fs.readFileSync(htmlPath, 'utf-8')
    } catch {
      return `<html><body><p style="color:red">Error: could not load chat.html from ${htmlPath}</p></body></html>`
    }

    // Convert local file paths to webview-safe URIs
    // (VS Code blocks direct file:// access from webviews for security)
    const cssUri = webview.asWebviewUri(vscode.Uri.file(cssPath))

    // Generate a random nonce for the Content Security Policy
    const nonce = getNonce()

    // Replace placeholders in the HTML template
    html = html
      .replace('{{CSS_URI}}', cssUri.toString())
      .replace(/{{NONCE}}/g, nonce)

    return html
  }
}

// ── Utility ───────────────────────────────────────────────────────────────────

function getNonce(): string {
  let text = ''
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length))
  }
  return text
}
