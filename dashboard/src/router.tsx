import { createBrowserRouter, Navigate } from 'react-router-dom'
import { getStoredCredentials } from '@/hooks/useApiKey'
import Layout from '@/components/shared/Layout'
import LoginPage from '@/pages/Login'
import OverviewPage from '@/pages/Overview'
import AgentsPage from '@/pages/Agents'
import AgentDetailPage from '@/pages/Agents/AgentDetail'
import MemoryPage from '@/pages/Memory'
import ActionsPage from '@/pages/Actions'
import EvaluationsPage from '@/pages/Evaluations'
import PromptsPage from '@/pages/Prompts'
import BlackboardPage from '@/pages/Blackboard'
import WebhooksPage from '@/pages/Webhooks'
import AuditLogPage from '@/pages/AuditLog'
import SettingsPage from '@/pages/Settings'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const creds = getStoredCredentials()
  if (!creds) return <Navigate to="/login" replace />
  return <>{children}</>
}

// In dev (Vite), BASE_URL is "/". In the production build (--base /dashboard/),
// BASE_URL is "/dashboard/" — React Router uses it as the basename so that
// hard-refreshing any sub-page works correctly when served by FastAPI.
export const router = createBrowserRouter(
  [
    {
      path: '/login',
      element: <LoginPage />,
    },
    {
      path: '/',
      element: (
        <RequireAuth>
          <Layout />
        </RequireAuth>
      ),
      children: [
        { index: true, element: <Navigate to="/overview" replace /> },
        { path: 'overview', element: <OverviewPage /> },
        { path: 'agents', element: <AgentsPage /> },
        { path: 'agents/:id', element: <AgentDetailPage /> },
        { path: 'memory', element: <MemoryPage /> },
        { path: 'actions', element: <ActionsPage /> },
        { path: 'evaluations', element: <EvaluationsPage /> },
        { path: 'prompts', element: <PromptsPage /> },
        { path: 'blackboard', element: <BlackboardPage /> },
        { path: 'webhooks', element: <WebhooksPage /> },
        { path: 'audit', element: <AuditLogPage /> },
        { path: 'settings', element: <SettingsPage /> },
      ],
    },
    { path: '*', element: <Navigate to="/" replace /> },
  ],
  { basename: import.meta.env.BASE_URL },
)
