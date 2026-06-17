import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { getProjects } from '../api/projects'
import type { ExplainMode, Project } from '../types'

type ProjectContextValue = {
  projects: Project[]
  selectedProject: Project | null
  explainMode: ExplainMode
  setSelectedProjectId: (id: string) => void
  setExplainMode: (mode: ExplainMode) => void
  isLoading: boolean
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [explainMode, setExplainMode] = useState<ExplainMode>('standard')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    getProjects()
      .then((list) => {
        setProjects(list)
        if (list.length > 0) setSelectedProjectId(list[0].id)
      })
      .finally(() => setIsLoading(false))
  }, [])

  const selectedProject = useMemo(
    () => projects.find((p) => p.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  )

  const setSelectedProjectIdStable = useCallback((id: string) => {
    setSelectedProjectId(id)
  }, [])

  const value = useMemo(
    () => ({
      projects,
      selectedProject,
      explainMode,
      setSelectedProjectId: setSelectedProjectIdStable,
      setExplainMode,
      isLoading,
    }),
    [projects, selectedProject, explainMode, setSelectedProjectIdStable, isLoading],
  )

  return (
    <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
  )
}

export function useProject() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used within ProjectProvider')
  return ctx
}
