import type { Report } from '../types'
import { apiRequest, tryApiOrMock } from './client'
import { mockGetReports } from './devMocks'

export async function getReports(): Promise<Report[]> {
  return tryApiOrMock(
    () => apiRequest<Report[]>('/reports'),
    () => mockGetReports(),
  )
}
