export type UserRole = 'admin' | 'developer' | 'auditor' | 'ci-robot'

export type ExplainMode = 'novice' | 'standard' | 'expert'

export type AuthUser = {
  id: string
  email: string
  name: string
  role: UserRole
}

export type AuthSession = {
  token: string
  user: AuthUser
}

export type Project = {
  id: string
  name: string
  repo: string
  branch: string
}

export type SourceCitation = {
  file: string
  lineStart: number
  lineEnd: number
  snippet: string
}

export type PatchDiffLine = {
  type: 'add' | 'remove' | 'context'
  lineNumber: number
  content: string
}

export type PatchProposal = {
  id: string
  title: string
  explanation: string
  risks: string[]
  testsRun: string[]
  confidence: number
  file: string
  diff: PatchDiffLine[]
  status: 'pending' | 'applied' | 'rejected'
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  sources?: SourceCitation[]
  patch?: PatchProposal
  streaming?: boolean
}

export type ConversationSummary = {
  id: string
  title: string
  projectId: string
  projectName: string
  messageCount: number
  lastMessageAt: string
  patchStatus?: 'pending' | 'applied' | 'rejected'
}

export type ConversationDetail = ConversationSummary & {
  messages: ChatMessage[]
}

export type Report = {
  id: string
  type: 'security' | 'audit' | 'patch' | 'indexing'
  title: string
  projectName: string
  createdAt: string
  summary: string
  severity?: 'low' | 'medium' | 'high'
}

export type AdminUser = {
  id: string
  email: string
  name: string
  role: UserRole
  lastLogin: string
}

export type AdminSettings = {
  maxTokensPerDay: number
  maxRequestsPerHour: number
  offlineMode: boolean
  defaultExplainMode: ExplainMode
}

export type ChatRequest = {
  message: string
  project: string
  explainMode: ExplainMode
  conversationId?: string
}

export type ChatResponse = {
  response: string
  conversationId: string
  sources?: SourceCitation[]
  patch?: PatchProposal
}
