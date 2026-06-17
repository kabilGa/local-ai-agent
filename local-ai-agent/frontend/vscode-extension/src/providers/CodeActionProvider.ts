/**
 * CodeActionProvider.ts
 *
 * Provides "quick-fix" lightbulb suggestions in the VS Code editor
 * for diagnostics created by DiagnosticsProvider.
 *
 * When the user hovers or clicks on a red/yellow squiggle from our
 * security scan, VS Code shows a lightbulb. Clicking it opens a menu
 * with options like "Ask AI Agent to fix this" or "Show explanation".
 *
 * Spec requirements fulfilled:
 *  - APPSEC-05: Propose secure fixes alongside findings
 *  - F-08: Always show diff before applying — the fix opens the chat
 *           panel with context pre-filled; actual patching goes through applyPatch.ts
 */

import * as vscode from 'vscode'

export class CodeActionProvider implements vscode.CodeActionProvider {
  public static readonly providedCodeActionKinds = [
    vscode.CodeActionKind.QuickFix,
  ]

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
  ): vscode.CodeAction[] {
    // Only provide actions for our own diagnostics (source = 'AI Agent Security Scan')
    const ourDiagnostics = context.diagnostics.filter(
      d => d.source === 'AI Agent Security Scan'
    )

    if (ourDiagnostics.length === 0) return []

    const actions: vscode.CodeAction[] = []

    for (const diagnostic of ourDiagnostics) {
      // Action 1: Ask AI Agent to fix this issue
      const fixAction = new vscode.CodeAction(
        `🤖 Ask AI Agent to fix: ${diagnostic.code}`,
        vscode.CodeActionKind.QuickFix
      )
      fixAction.diagnostics = [diagnostic]
      // Triggers the askAboutSelection command with the finding pre-filled
      fixAction.command = {
        command: 'localAiAgent.askAboutSelection',
        title: 'Ask AI Agent to fix this security issue',
        arguments: [
          document.uri,
          range,
          `Fix this security issue: [${diagnostic.code}] ${diagnostic.message}`,
        ],
      }
      fixAction.isPreferred = true
      actions.push(fixAction)

      // Action 2: Explain this finding
      const explainAction = new vscode.CodeAction(
        `💡 Explain: ${diagnostic.code}`,
        vscode.CodeActionKind.QuickFix
      )
      explainAction.diagnostics = [diagnostic]
      explainAction.command = {
        command: 'localAiAgent.askAboutSelection',
        title: 'Explain this security finding',
        arguments: [
          document.uri,
          range,
          `Explain this security finding and how to fix it: [${diagnostic.code}] ${diagnostic.message}`,
        ],
      }
      actions.push(explainAction)
    }

    return actions
  }
}
