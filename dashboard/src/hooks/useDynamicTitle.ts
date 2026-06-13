import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

const ROUTE_TITLES: Record<string, string> = {
  '/overview': 'Overview',
  '/agents': 'Agents',
  '/memory': 'Memory',
  '/actions': 'Actions',
  '/evaluations': 'Evaluations',
  '/prompts': 'Prompts',
  '/blackboard': 'Blackboard',
  '/webhooks': 'Webhooks',
  '/audit': 'Audit Log',
  '/settings': 'Settings',
}

export function useDynamicTitle() {
  const { pathname } = useLocation()

  useEffect(() => {
    const base = 'CrewLayer'
    const segment = Object.entries(ROUTE_TITLES).find(([path]) =>
      pathname === path || pathname.startsWith(path + '/'),
    )
    document.title = segment ? `${segment[1]} · ${base}` : base
  }, [pathname])
}
