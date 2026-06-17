import type {
  AdminSettings,
  AdminUser,
  AuthSession,
  ChatRequest,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  PatchProposal,
  Project,
  Report,
  SourceCitation,
} from '../types'

export const MOCK_PROJECTS: Project[] = [
  { id: 'proj-1', name: 'web-portal', repo: 'frontend/web-portal', branch: 'main' },
  { id: 'proj-2', name: 'api-gateway', repo: 'services/api-gateway', branch: 'develop' },
  { id: 'proj-3', name: 'rag-engine', repo: 'services/rag-engine', branch: 'main' },
]

const MOCK_SOURCES: SourceCitation[] = [
  {
    file: 'src/components/ChatPage.tsx',
    lineStart: 32,
    lineEnd: 45,
    snippet: 'const res = await fetch(\'/chat\', { method: \'POST\', ... })',
  },
  {
    file: 'openapi.yaml',
    lineStart: 12,
    lineEnd: 18,
    snippet: 'paths:\n  /chat:\n    post:',
  },
]

const MOCK_PATCH: PatchProposal = {
  id: 'patch-001',
  title: 'Add null check before fetch',
  explanation:
    'The chat handler should validate the input before calling the API to avoid empty requests.',
  risks: ['Low risk — only adds a guard clause'],
  testsRun: ['npm run lint', 'npm run build'],
  confidence: 0.92,
  file: 'src/components/ChatPage.tsx',
  diff: [
    { type: 'context', lineNumber: 14, content: '  async function handleSend(event: FormEvent) {' },
    { type: 'context', lineNumber: 15, content: '    event.preventDefault()' },
    { type: 'add', lineNumber: 16, content: '    if (!input.trim()) return' },
    { type: 'context', lineNumber: 17, content: '' },
    { type: 'remove', lineNumber: 18, content: '    const trimmed = input' },
    { type: 'add', lineNumber: 18, content: '    const trimmed = input.trim()' },
  ],
  status: 'pending',
}

const conversations: ConversationSummary[] = [
  {
    id: 'conv-1',
    title: 'Fix chat API error handling',
    projectId: 'proj-1',
    projectName: 'web-portal',
    messageCount: 4,
    lastMessageAt: '2026-06-13T14:30:00Z',
    patchStatus: 'applied',
  },
  {
    id: 'conv-2',
    title: 'Review auth token expiry',
    projectId: 'proj-2',
    projectName: 'api-gateway',
    messageCount: 6,
    lastMessageAt: '2026-06-12T09:15:00Z',
    patchStatus: 'pending',
  },
  {
    id: 'conv-3',
    title: 'Index new repository files',
    projectId: 'proj-3',
    projectName: 'rag-engine',
    messageCount: 3,
    lastMessageAt: '2026-06-11T16:45:00Z',
  },
]

const reports: Report[] = [
  {
    id: 'rpt-1',
    type: 'security',
    title: 'SAST scan — web-portal',
    projectName: 'web-portal',
    createdAt: '2026-06-13T08:00:00Z',
    summary: '0 critical, 2 medium findings in dependencies.',
    severity: 'medium',
  },
  {
    id: 'rpt-2',
    type: 'patch',
    title: 'Patch audit trail',
    projectName: 'api-gateway',
    createdAt: '2026-06-12T17:30:00Z',
    summary: '1 patch applied, 1 rejected by developer.',
    severity: 'low',
  },
  {
    id: 'rpt-3',
    type: 'indexing',
    title: 'Repository index report',
    projectName: 'rag-engine',
    createdAt: '2026-06-11T10:00:00Z',
    summary: '1,247 files indexed, 3 parsing warnings.',
    severity: 'low',
  },
  {
    id: 'rpt-4',
    type: 'audit',
    title: 'Weekly access audit',
    projectName: 'all',
    createdAt: '2026-06-10T23:59:00Z',
    summary: '42 API calls logged, 0 policy violations.',
    severity: 'low',
  },
]

const adminUsers: AdminUser[] = [
  {
    id: 'u-1',
    email: 'dev@local.agent',
    name: 'Developer User',
    role: 'developer',
    lastLogin: '2026-06-14T08:00:00Z',
  },
  {
    id: 'u-2',
    email: 'admin@local.agent',
    name: 'Admin User',
    role: 'admin',
    lastLogin: '2026-06-14T07:30:00Z',
  },
  {
    id: 'u-3',
    email: 'auditor@local.agent',
    name: 'Auditor User',
    role: 'auditor',
    lastLogin: '2026-06-13T18:00:00Z',
  },
]

const adminSettings: AdminSettings = {
  maxTokensPerDay: 500_000,
  maxRequestsPerHour: 120,
  offlineMode: true,
  defaultExplainMode: 'standard',
}

const patchStore = new Map<string, PatchProposal>([['patch-001', { ...MOCK_PATCH }]])

function explainPrefix(mode: ChatRequest['explainMode']): string {
  if (mode === 'novice') {
    return '[Novice mode] Here is a simple explanation: '
  }
  if (mode === 'expert') {
    return '[Expert mode] Technical analysis: '
  }
  return ''
}

export function mockLogin(email: string, _password: string): AuthSession {
  const role =
    email.includes('admin') ? 'admin' : email.includes('audit') ? 'auditor' : 'developer'
  return {
    token: `mock-jwt-${crypto.randomUUID()}`,
    user: {
      id: crypto.randomUUID(),
      email,
      name: email.split('@')[0],
      role,
    },
  }
}

export function mockChat(request: ChatRequest): ChatResponse {
  const lower = request.message.toLowerCase()
  const wantsPatch =
    lower.includes('patch') || lower.includes('fix') || lower.includes('bug')

  const base =
    explainPrefix(request.explainMode) +
    'I analyzed your request locally. No data left your machine.'

  if (wantsPatch) {
    const patch = { ...MOCK_PATCH, id: `patch-${Date.now()}`, status: 'pending' as const }
    patchStore.set(patch.id, patch)
    return {
      response:
        base +
        ' I found a likely fix and prepared a patch for your review. Please check the diff below and accept or reject.',
      conversationId: request.conversationId ?? `conv-${Date.now()}`,
      sources: MOCK_SOURCES,
      patch,
    }
  }

  return {
    response:
      base +
      ' Based on the indexed codebase, the relevant handler looks like this:\n\n```typescript\nconst res = await fetch("/chat", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify({ message, project }),\n})\n```\n\nSee cited sources below for file locations.',
    conversationId: request.conversationId ?? `conv-${Date.now()}`,
    sources: MOCK_SOURCES,
  }
}

export function mockGetProjects(): Project[] {
  return MOCK_PROJECTS
}

export function mockGetConversations(): ConversationSummary[] {
  return conversations
}

export function mockGetConversation(id: string): ConversationDetail | null {
  const summary = conversations.find((c) => c.id === id)
  if (!summary) return null
  return {
    ...summary,
    messages: [
      {
        id: 'm-1',
        role: 'user',
        text: 'Can you help me fix the chat error handling?',
      },
      {
        id: 'm-2',
        role: 'assistant',
        text: 'I found the issue in ChatPage.tsx. A patch is available for review.',
        sources: MOCK_SOURCES,
        patch: MOCK_PATCH,
      },
    ],
  }
}

export function mockGetPatch(id: string): PatchProposal | null {
  return patchStore.get(id) ?? (id === MOCK_PATCH.id ? MOCK_PATCH : null)
}

export function mockApplyPatch(id: string): PatchProposal {
  const patch = patchStore.get(id) ?? MOCK_PATCH
  const applied = { ...patch, status: 'applied' as const }
  patchStore.set(id, applied)
  return applied
}

export function mockRejectPatch(id: string): PatchProposal {
  const patch = patchStore.get(id) ?? MOCK_PATCH
  const rejected = { ...patch, status: 'rejected' as const }
  patchStore.set(id, rejected)
  return rejected
}

export function mockGetReports(): Report[] {
  return reports
}

export function mockGetAdminUsers(): AdminUser[] {
  return adminUsers
}

export function mockGetAdminSettings(): AdminSettings {
  return adminSettings
}
