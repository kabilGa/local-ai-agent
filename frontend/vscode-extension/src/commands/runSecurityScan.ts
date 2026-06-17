/**
 * runSecurityScan.ts
 *
 * Triggers a SAST/SCA security scan via the AI Agent API Gateway.
 * Results are pushed to VS Code's Problems panel via DiagnosticsProvider.
 *
 * Two variants:
 *  - runSecurityScanFile      : scan the currently open file
 *  - runSecurityScanWorkspace : scan the entire workspace/project
 *
 * Spec requirements fulfilled:
 *  - APPSEC-01: Defensive code security reviews
 *  - APPSEC-02: Integrate/orchestrate SAST, SCA, secret scanning
 *  - APPSEC-03: Map to OWASP Top 10, CWE, CVE/CVSS
 *  - APPSEC-04: Prioritise by exploitability and severity
 */

import * as vscode from 'vscode'
import * as agentClient from '../api/agentClient'
import { DiagnosticsProvider } from '../providers/DiagnosticsProvider'

/**
 * Scan the currently active file and publish findings to the Problems panel.
 */
export async function runSecurityScanFile(
  diagnosticsProvider: DiagnosticsProvider
): Promise<void> {
  const editor = vscode.window.activeTextEditor
  if (!editor) {
    vscode.window.showWarningMessage('AI Agent: Open a file to scan.')
    return
  }

  const filePath = vscode.workspace.asRelativePath(editor.document.uri)
  const projectId = agentClient.getDefaultProject()

  if (!projectId) {
    vscode.window.showWarningMessage(
      'AI Agent: Set a default project in Settings (localAiAgent.defaultProject) before scanning.'
    )
    return
  }

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `AI Agent: Scanning ${filePath}…`,
      cancellable: false,
    },
    async () => {
      try {
        const result = await agentClient.runSecurityScan(filePath, projectId)

        // Clear old findings for this file first to avoid stale entries
        diagnosticsProvider.clearFile(editor.document.uri)
        diagnosticsProvider.publishFindings(result.findings)

        const count = result.findings.length
        if (count === 0) {
          vscode.window.showInformationMessage(
            `✅ AI Agent: No security issues found in ${filePath}.`
          )
        } else {
          vscode.window.showWarningMessage(
            `⚠️ AI Agent: Found ${count} issue${count === 1 ? '' : 's'} in ${filePath}. See Problems panel.`
          )
          // Open the Problems panel automatically so the user sees results
          vscode.commands.executeCommand('workbench.panel.markers.view.focus')
        }
      } catch (err) {
        vscode.window.showErrorMessage(
          `AI Agent Security Scan failed: ${(err as Error).message}`
        )
      }
    }
  )
}

/**
 * Scan the entire workspace and publish all findings to the Problems panel.
 */
export async function runSecurityScanWorkspace(
  diagnosticsProvider: DiagnosticsProvider
): Promise<void> {
  const projectId = agentClient.getDefaultProject()

  if (!projectId) {
    vscode.window.showWarningMessage(
      'AI Agent: Set a default project in Settings (localAiAgent.defaultProject) before scanning.'
    )
    return
  }

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: 'AI Agent: Running workspace security scan…',
      cancellable: false,
    },
    async () => {
      try {
        const result = await agentClient.runWorkspaceScan(projectId)

        // Replace ALL previous findings with fresh results
        diagnosticsProvider.clearAll()
        diagnosticsProvider.publishFindings(result.findings)

        const count = result.findings.length
        const fileCount = result.scannedFiles

        if (count === 0) {
          vscode.window.showInformationMessage(
            `✅ AI Agent: No security issues found across ${fileCount} files.`
          )
        } else {
          vscode.window.showWarningMessage(
            `⚠️ AI Agent: Found ${count} issue${count === 1 ? '' : 's'} across ${fileCount} files. See Problems panel.`
          )
          vscode.commands.executeCommand('workbench.panel.markers.view.focus')
        }
      } catch (err) {
        vscode.window.showErrorMessage(
          `AI Agent Workspace Scan failed: ${(err as Error).message}`
        )
      }
    }
  )
}
