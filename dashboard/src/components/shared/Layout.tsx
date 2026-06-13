import { useState, createContext, useContext } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { ErrorBoundary } from './ErrorBoundary'
import { CommandPalette } from './CommandPalette'
import { useDynamicTitle } from '@/hooks/useDynamicTitle'

interface SidebarCtx {
  mobileOpen: boolean
  setMobileOpen: (v: boolean) => void
}

export const SidebarContext = createContext<SidebarCtx>({ mobileOpen: false, setMobileOpen: () => {} })
export const useSidebar = () => useContext(SidebarContext)

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  useDynamicTitle()

  return (
    <SidebarContext.Provider value={{ mobileOpen, setMobileOpen }}>
      <div className="flex h-screen overflow-hidden bg-background">
        {/* Mobile backdrop */}
        {mobileOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/60 lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
        )}

        {/* Sidebar */}
        <div className={`fixed inset-y-0 left-0 z-40 lg:relative lg:h-full lg:block lg:z-auto transition-transform duration-200 ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
          <Sidebar />
        </div>

        <div className="flex flex-1 flex-col overflow-hidden min-w-0">
          <Header />
          <main className="flex-1 overflow-y-auto">
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
      <CommandPalette />
    </SidebarContext.Provider>
  )
}
