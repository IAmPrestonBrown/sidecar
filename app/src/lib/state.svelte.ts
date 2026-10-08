import { get } from './api'
import type { ProjectMeta, ProjectSummary } from './types'

export type Page =
  | 'today'
  | 'inbox'
  | 'hypotheses'
  | 'hypothesis'
  | 'evidence'
  | 'brief'
  | 'queue'
  | 'people'
  | 'person'
  | 'organizations'
  | 'find'
  | 'calls'
  | 'call'
  | 'settings'

export interface Route {
  page: Page
  id: string
}

const LAST_PROJECT_KEY = 'sidecar.project'

function parseHash(): Route {
  const [page, id] = location.hash.replace(/^#\/?/, '').split('/')
  return { page: (page || 'today') as Page, id: id ?? '' }
}

class AppState {
  route = $state<Route>(parseHash())
  projects = $state<ProjectSummary[]>([])
  slug = $state('')
  /** Segment names for the current project, from its research brief. */
  segments = $state<string[]>([])
  /** Bumped after any change so open pages and the sidebar reload. */
  version = $state(0)

  constructor() {
    window.addEventListener('hashchange', () => {
      this.route = parseHash()
    })
  }

  get project(): ProjectSummary | undefined {
    return this.projects.find((p) => p.slug === this.slug)
  }

  /** Path prefix for the current project's API routes. */
  get base(): string {
    return `/projects/${this.slug}`
  }

  go(page: Page, id = ''): void {
    location.hash = id ? `#/${page}/${id}` : `#/${page}`
  }

  changed(): void {
    this.version += 1
  }

  async loadSegments(): Promise<void> {
    this.segments = this.slug ? (await get<ProjectMeta>(this.base)).segments : []
  }

  async loadProjects(): Promise<void> {
    this.projects = await get<ProjectSummary[]>('/projects')
    const saved = localStorage.getItem(LAST_PROJECT_KEY) ?? ''
    const pick = this.projects.find((p) => p.slug === saved) ?? this.projects[0]
    this.slug = pick?.slug ?? ''
    await this.loadSegments()
  }

  selectProject(slug: string): void {
    this.slug = slug
    localStorage.setItem(LAST_PROJECT_KEY, slug)
    void this.loadSegments()
    this.go('today')
    this.changed()
  }
}

export const app = new AppState()
