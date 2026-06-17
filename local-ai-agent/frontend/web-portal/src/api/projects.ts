import type { Project } from '../types'
import { apiRequest, tryApiOrMock } from './client'
import { mockGetProjects } from './devMocks'

export async function getProjects(): Promise<Project[]> {
  return tryApiOrMock(
    () => apiRequest<Project[]>('/projects'),
    () => mockGetProjects(),
  )
}
