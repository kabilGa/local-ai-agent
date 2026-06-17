/**
 * DiagnosticsProvider.ts
 *
 * Converts AI security scan results into VS Code Diagnostics,
 * which appear in the built-in Problems panel (the same panel that
 * shows TypeScript errors, ESLint warnings, etc.).
 *
 * Spec requirements fulfilled:
 *  - APPSEC-01: Code security review findings surfaced to developer
 *  - APPSEC-02: SAST/SCA results integrated into IDE
 *  - APPSEC-03: Findings mapped to OWASP / CWE categories
 *  - APPSEC-04: Priority shown via severity (error/warning/info)
 */

import * as vscode from 'vscode'
import type { SecurityFinding } from '../api/agentClient'

export class DiagnosticsProvider {
  /** The DiagnosticCollection is the "channel" for our Problems panel entries. */
  private collection: vscode.DiagnosticCollection

  constructor() {
    // 'localAiAgent' is the source label shown in the Problems panel
    this.collection = vscode.languages.createDiagnosticCollection('localAiAgent')
  }

  /**
   * Push an array of SecurityFindings to the Problems panel.
   * Groups findings by file so VS Code can display them correctly.
   */
  public publishFindings(findings: SecurityFinding[]): void {
    // Group findings by file path
    const byFile = new Map<string, SecurityFinding[]>()
    for (const f of findings) {
      if (!byFile.has(f.file)) byFile.set(f.file, [])
      byFile.get(f.file)!.push(f)
    }

    // For each file, create VS Code Diagnostic objects and set them
    for (const [filePath, filefindings] of byFile.entries()) {
      const uri = vscode.Uri.file(filePath)
      const diagnostics = filefindings.map(f => this.toDiagnostic(f))
      this.collection.set(uri, diagnostics)
    }
  }

  /**
   * Convert a single SecurityFinding → vscode.Diagnostic
   */
  private toDiagnostic(finding: SecurityFinding): vscode.Diagnostic {
    // VS Code lines are 0-indexed; our API returns 1-indexed line numbers
    const startLine = Math.max(0, (finding.line || 1) - 1)
    const endLine = Math.max(startLine, (finding.endLine || finding.line || 1) - 1)

    // Use a full-line range if we don't have column info
    const range = new vscode.Range(
      new vscode.Position(startLine, 0),
      new vscode.Position(endLine, Number.MAX_SAFE_INTEGER)
    )

    const severity = this.mapSeverity(finding.severity)

    // Include the category (OWASP/CWE) in the message for traceability (APPSEC-03)
    const message = `[${finding.ruleId}] ${finding.message} — ${finding.category}`

    const diagnostic = new vscode.Diagnostic(range, message, severity)
    diagnostic.source = 'AI Agent Security Scan'
    diagnostic.code = finding.ruleId

    return diagnostic
  }

  private mapSeverity(severity: SecurityFinding['severity']): vscode.DiagnosticSeverity {
    switch (severity) {
      case 'error':   return vscode.DiagnosticSeverity.Error
      case 'warning': return vscode.DiagnosticSeverity.Warning
      case 'info':    return vscode.DiagnosticSeverity.Information
      default:        return vscode.DiagnosticSeverity.Warning
    }
  }

  /** Clear all diagnostics for a specific file. */
  public clearFile(uri: vscode.Uri): void {
    this.collection.delete(uri)
  }

  /** Clear ALL diagnostics from the Problems panel. */
  public clearAll(): void {
    this.collection.clear()
  }

  /** Must be called when the extension deactivates to free resources. */
  public dispose(): void {
    this.collection.dispose()
  }
}
