import type { PatchProposal } from '../types'
import { apiRequest, tryApiOrMock } from './client'
import { mockApplyPatch, mockGetPatch, mockRejectPatch } from './devMocks'

export async function getPatch(id: string): Promise<PatchProposal | null> {
  return tryApiOrMock(
    () => apiRequest<PatchProposal>(`/patches/${id}`),
    () => mockGetPatch(id),
  )
}

export async function applyPatch(id: string): Promise<PatchProposal> {
  return tryApiOrMock(
    () => apiRequest<PatchProposal>(`/patches/${id}/apply`, { method: 'POST' }),
    () => mockApplyPatch(id),
  )
}

export async function rejectPatch(id: string): Promise<PatchProposal> {
  return tryApiOrMock(
    () => apiRequest<PatchProposal>(`/patches/${id}/reject`, { method: 'POST' }),
    () => mockRejectPatch(id),
  )
}
