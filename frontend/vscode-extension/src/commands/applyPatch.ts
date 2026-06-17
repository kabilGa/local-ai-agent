/**
 * applyPatch.ts
 *
 * Implements the human-in-the-loop patch review flow:
 *
 *   1. Fetch patch proposal from API
 *   2. Write "before" and "after" versions as temp files
 *   3. Open VS Code's native diff editor (side-by-side view)
 *   4. Show a confirmation modal: "Apply this patch?"
 *   5. Only apply if user explicitly clicks Apply
 *   6. Call API to record apply/reject decision
 *   7. Clean up temp files
 *
 * Spec requirements fulfilled:
 *  - F-08: Display diff before any modification
 *  - F-09: Allow reject/rollback
 *  - (arch): Human-in-the-loop — never auto-apply
 *  - QAI-03: All actions logged via API call
 */

import * as vscode from 'vscode'
import * as fs from 'fs'
import * as path from 'path'
import * as os from 'os'
import * as agentClient from '../api/agentClient'

/**
 * Show a patch proposal in a diff editor and ask for confirmation.
 * @param patchId - The patch ID returned by the chat API response
 */
export async function showAndApplyPatch(patchId: string): Promise<void> {
  // ── Step 1: Fetch the patch details ──────────────────────────────────────
  let patch: agentClient.PatchProposal

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'AI Agent: Loading patch…', cancellable: false },
    async () => {
      patch = await agentClient.getPatch(patchId)
    }
  )

  patch = patch!

  if (!patch.diff) {
    vscode.window.showWarningMessage('AI Agent: Patch has no diff content.')
    return
  }

  // ── Step 2: Parse the unified diff to extract before/after content ────────
  const { before, after, targetFile } = parseDiff(patch.diff)

  // ── Step 3: Write temp files for the diff viewer ──────────────────────────
  const tmpDir = os.tmpdir()
  const safeName = (targetFile || 'patch').replace(/[^a-zA-Z0-9._-]/g, '_')
  const beforePath = path.join(tmpDir, `ai-agent-before-${safeName}`)
  const afterPath  = path.join(tmpDir, `ai-agent-after-${safeName}`)

  fs.writeFileSync(beforePath, before, 'utf-8')
  fs.writeFileSync(afterPath, after, 'utf-8')

  const beforeUri = vscode.Uri.file(beforePath)
  const afterUri  = vscode.Uri.file(afterPath)

  // ── Step 4: Open VS Code's native diff editor ─────────────────────────────
  // This gives the developer a real, colour-coded side-by-side diff
  await vscode.commands.executeCommand(
    'vscode.diff',
    beforeUri,
    afterUri,
    `AI Agent Patch: ${patch.title} (read-only preview)`
  )

  // ── Step 5: Show explanation + confirmation dialog ────────────────────────
  const explanation =
    `**${patch.title}**\n\n` +
    `${patch.explanation}\n\n` +
    `Do you want to apply this patch to your workspace?`

  const choice = await vscode.window.showInformationMessage(
    `AI Agent — ${patch.title}`,
    { modal: true, detail: patch.explanation },
    'Apply Patch',
    'Reject'
  )

  // ── Step 6: Record decision with API ─────────────────────────────────────
  if (choice === 'Apply Patch') {
    try {
      // Apply the actual file changes in the workspace
      await applyDiffToWorkspace(targetFile, after)
      // Record the apply action via API (for audit trail — QAI-03)
      await agentClient.applyPatch(patchId)
      vscode.window.showInformationMessage(`✅ AI Agent: Patch applied successfully.`)
    } catch (err) {
      vscode.window.showErrorMessage(`AI Agent: Failed to apply patch — ${(err as Error).message}`)
    }
  } else if (choice === 'Reject') {
    await agentClient.rejectPatch(patchId)
    vscode.window.showInformationMessage('❌ AI Agent: Patch rejected and recorded.')
  }
  // If user closed the dialog without choosing, do nothing (safe default)

  // ── Step 7: Clean up temp files ───────────────────────────────────────────
  try {
    fs.unlinkSync(beforePath)
    fs.unlinkSync(afterPath)
  } catch {
    // Non-critical — temp files will be cleaned by OS eventually
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Parse a unified diff string into before/after content strings.
 * Handles simple single-file diffs (the most common case from the API).
 */
function parseDiff(diff: string): { before: string; after: string; targetFile: string } {
  const lines = diff.split('\n')
  const beforeLines: string[] = []
  const afterLines: string[] = []
  let targetFile = 'patched_file'

  for (const line of lines) {
    if (line.startsWith('--- ')) {
      // "--- a/src/foo.ts" → extract file name
      targetFile = line.replace(/^--- [ab]\//, '')
      continue
    }
    if (line.startsWith('+++ ')) continue
    if (line.startsWith('@@')) continue
    if (line.startsWith('diff ') || line.startsWith('index ')) continue

    if (line.startsWith('-')) {
      beforeLines.push(line.slice(1))
    } else if (line.startsWith('+')) {
      afterLines.push(line.slice(1))
    } else {
      // Context line (no prefix) — appears in both
      beforeLines.push(line)
      afterLines.push(line)
    }
  }

  return {
    before: beforeLines.join('\n'),
    after: afterLines.join('\n'),
    targetFile,
  }
}

/**
 * Write the patched content to the actual workspace file.
 * Uses VS Code's WorkspaceEdit API so the change appears in the editor
 * and is undoable with Ctrl+Z.
 */
async function applyDiffToWorkspace(relativeFilePath: string, newContent: string): Promise<void> {
  const workspaceFolders = vscode.workspace.workspaceFolders
  if (!workspaceFolders || workspaceFolders.length === 0) {
    throw new Error('No workspace folder open.')
  }

  const rootUri = workspaceFolders[0].uri
  const fileUri = vscode.Uri.joinPath(rootUri, relativeFilePath)

  const edit = new vscode.WorkspaceEdit()

  try {
    // If file exists, replace its entire content
    const doc = await vscode.workspace.openTextDocument(fileUri)
    const fullRange = new vscode.Range(
      doc.lineAt(0).range.start,
      doc.lineAt(doc.lineCount - 1).range.end
    )
    edit.replace(fileUri, fullRange, newContent)
  } catch {
    // File doesn't exist — create it
    edit.createFile(fileUri, { overwrite: false })
    edit.insert(fileUri, new vscode.Position(0, 0), newContent)
  }

  const success = await vscode.workspace.applyEdit(edit)
  if (!success) {
    throw new Error('VS Code rejected the workspace edit.')
  }
}
