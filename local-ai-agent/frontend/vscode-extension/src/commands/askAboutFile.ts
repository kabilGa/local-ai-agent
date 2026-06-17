/**
 * askAboutFile.ts
 *
 * Two commands:
 *  - localAiAgent.askAboutFile    : sends the entire active file to the AI
 *  - localAiAgent.askAboutSelection: sends only the selected code snippet
 *
 * Both commands open the Chat panel (sidebar) and pre-fill the input
 * with context about the file/selection so the user just needs to refine
 * their question rather than copy-pasting code manually.
 *
 * Spec: F-01 (conversational interface), F-07 (sourced responses),
 *       DEV-05 (explain existing code)
 */

import * as vscode from 'vscode'
import { ChatPanel } from '../panels/ChatPanel'

/**
 * Ask AI about the currently open file.
 * Sends the file name, language, and full content as context.
 */
export async function askAboutFileCommand(
  chatPanel: ChatPanel,
  uri?: vscode.Uri
): Promise<void> {
  // Resolve the file: either the right-clicked file (uri arg) or the active editor
  let document: vscode.TextDocument

  if (uri) {
    document = await vscode.workspace.openTextDocument(uri)
  } else if (vscode.window.activeTextEditor) {
    document = vscode.window.activeTextEditor.document
  } else {
    vscode.window.showWarningMessage('AI Agent: No file is open. Open a file first.')
    return
  }

  const fileName = vscode.workspace.asRelativePath(document.uri)
  const language = document.languageId
  const content = document.getText()

  // Truncate very large files to avoid hitting context limits
  const MAX_CHARS = 12_000
  const truncated = content.length > MAX_CHARS
  const excerpt = content.slice(0, MAX_CHARS)

  const contextMessage =
    `Please analyse the following ${language} file: \`${fileName}\`\n` +
    (truncated ? `*(showing first ${MAX_CHARS} characters)*\n` : '') +
    `\n\`\`\`${language}\n${excerpt}\n\`\`\`\n\n` +
    `What are the main responsibilities of this file, and are there any issues I should know about?`

  // Open the chat panel and send the pre-filled message
  await chatPanel.show()
  chatPanel.sendPrefilled(contextMessage)
}

/**
 * Ask AI about the currently selected code snippet.
 * Can also be called programmatically from CodeActionProvider with a custom prompt.
 */
export async function askAboutSelectionCommand(
  chatPanel: ChatPanel,
  uri?: vscode.Uri,
  range?: vscode.Range | vscode.Selection,
  customPrompt?: string
): Promise<void> {
  const editor = vscode.window.activeTextEditor

  if (!editor && !uri) {
    vscode.window.showWarningMessage('AI Agent: No editor is active.')
    return
  }

  // Use the provided range/uri or fall back to the current selection
  const targetEditor = editor
  const targetRange = range || targetEditor?.selection
  const targetDoc = uri
    ? await vscode.workspace.openTextDocument(uri)
    : targetEditor?.document

  if (!targetDoc || !targetRange || targetRange.isEmpty) {
    vscode.window.showWarningMessage('AI Agent: Please select some code first.')
    return
  }

  const fileName = vscode.workspace.asRelativePath(targetDoc.uri)
  const language = targetDoc.languageId
  const selectedText = targetDoc.getText(targetRange)
  const startLine = targetRange.start.line + 1 // convert to 1-indexed for display

  const contextMessage = customPrompt
    ? `${customPrompt}\n\nContext — \`${fileName}\` line ${startLine}:\n\`\`\`${language}\n${selectedText}\n\`\`\``
    : `Please explain this code from \`${fileName}\` (line ${startLine}):\n\n\`\`\`${language}\n${selectedText}\n\`\`\`\n\nAre there any improvements or issues I should address?`

  await chatPanel.show()
  chatPanel.sendPrefilled(contextMessage)
}
