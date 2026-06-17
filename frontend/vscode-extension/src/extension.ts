/**
 * extension.ts — Entry point for the Local AI Agent VS Code extension.
 *
 * VS Code calls activate() when the extension first loads.
 * VS Code calls deactivate() when the extension is unloaded / VS Code closes.
 *
 * All commands, providers, and panels are registered here and stored in the
 * context.subscriptions array so VS Code can clean them up automatically.
 *
 * Think of this file like main.tsx in your React app — it boots everything.
 */

import * as vscode from 'vscode'
import { ChatPanel } from './panels/ChatPanel'
import { DiagnosticsProvider } from './providers/DiagnosticsProvider'
import { CodeActionProvider } from './providers/CodeActionProvider'
import { askAboutFileCommand, askAboutSelectionCommand } from './commands/askAboutFile'
import { showAndApplyPatch } from './commands/applyPatch'
import { runSecurityScanFile, runSecurityScanWorkspace } from './commands/runSecurityScan'

export function activate(context: vscode.ExtensionContext): void {
  console.log('[AI Agent] Extension activating…')

  // ── 1. Instantiate shared services ──────────────────────────────────────
  const diagnosticsProvider = new DiagnosticsProvider()
  const chatPanel = new ChatPanel(context.extensionUri)

  // ── 2. Register the sidebar WebviewView provider ─────────────────────────
  // This tells VS Code: "when localAiAgent.chatView is shown in the sidebar,
  // call chatPanel.resolveWebviewView() to build the HTML."
  const webviewProvider = vscode.window.registerWebviewViewProvider(
    ChatPanel.viewId,
    chatPanel,
    {
      // Keep the webview alive even when the sidebar panel is hidden.
      // Without this, the chat history would reset every time you switch tabs.
      webviewOptions: { retainContextWhenHidden: true },
    }
  )

  // ── 3. Register CodeAction provider (lightbulb quick-fixes) ─────────────
  const codeActionProvider = vscode.languages.registerCodeActionsProvider(
    { pattern: '**/*' }, // apply to all file types
    new CodeActionProvider(),
    { providedCodeActionKinds: CodeActionProvider.providedCodeActionKinds }
  )

  // ── 4. Register all commands ─────────────────────────────────────────────

  /** Open / focus the chat panel in the sidebar */
  const cmdOpenChat = vscode.commands.registerCommand(
    'localAiAgent.openChat',
    async () => {
      await chatPanel.show()
    }
  )

  /** Right-click a file → "Ask AI Agent About This File" */
  const cmdAskAboutFile = vscode.commands.registerCommand(
    'localAiAgent.askAboutFile',
    async (uri?: vscode.Uri) => {
      await askAboutFileCommand(chatPanel, uri)
    }
  )

  /** Right-click selected code → "Ask AI Agent About Selected Code" */
  const cmdAskAboutSelection = vscode.commands.registerCommand(
    'localAiAgent.askAboutSelection',
    async (uri?: vscode.Uri, range?: vscode.Range, customPrompt?: string) => {
      await askAboutSelectionCommand(chatPanel, uri, range, customPrompt)
    }
  )

  /** Security scan — current file only */
  const cmdScanFile = vscode.commands.registerCommand(
    'localAiAgent.runSecurityScan',
    async () => {
      await runSecurityScanFile(diagnosticsProvider)
    }
  )

  /** Security scan — entire workspace */
  const cmdScanWorkspace = vscode.commands.registerCommand(
    'localAiAgent.runSecurityScanWorkspace',
    async () => {
      await runSecurityScanWorkspace(diagnosticsProvider)
    }
  )

  /** Clear all security diagnostics from the Problems panel */
  const cmdClearDiagnostics = vscode.commands.registerCommand(
    'localAiAgent.clearDiagnostics',
    () => {
      diagnosticsProvider.clearAll()
      vscode.window.showInformationMessage('AI Agent: Diagnostics cleared.')
    }
  )

  // ── 5. Configuration change listener ────────────────────────────────────
  // If the user updates settings (apiUrl, token, etc.), log it.
  // In future this could refresh the projects list in the chat panel.
  const configWatcher = vscode.workspace.onDidChangeConfiguration((e) => {
    if (e.affectsConfiguration('localAiAgent')) {
      console.log('[AI Agent] Configuration updated.')
    }
  })

  // ── 6. Show welcome message on first install ─────────────────────────────
  const hasActivatedBefore = context.globalState.get<boolean>('hasActivatedBefore')
  if (!hasActivatedBefore) {
    vscode.window
      .showInformationMessage(
        '👋 Local AI Agent is ready! Open the AI Agent panel in the sidebar to start chatting.',
        'Open Chat',
        'Configure Settings'
      )
      .then((choice) => {
        if (choice === 'Open Chat') {
          vscode.commands.executeCommand('localAiAgent.openChat')
        } else if (choice === 'Configure Settings') {
          vscode.commands.executeCommand(
            'workbench.action.openSettings',
            'localAiAgent'
          )
        }
      })
    context.globalState.update('hasActivatedBefore', true)
  }

  // ── 7. Register everything for automatic cleanup on deactivate ───────────
  context.subscriptions.push(
    webviewProvider,
    codeActionProvider,
    cmdOpenChat,
    cmdAskAboutFile,
    cmdAskAboutSelection,
    cmdScanFile,
    cmdScanWorkspace,
    cmdClearDiagnostics,
    configWatcher,
    // DiagnosticsProvider owns a DiagnosticCollection that must be disposed
    { dispose: () => diagnosticsProvider.dispose() }
  )

  console.log('[AI Agent] Extension activated successfully.')
}

export function deactivate(): void {
  // VS Code automatically calls dispose() on everything in context.subscriptions.
  // Nothing extra needed here.
  console.log('[AI Agent] Extension deactivated.')
}
