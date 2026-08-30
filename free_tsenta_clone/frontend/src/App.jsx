import { useEffect, useState } from 'react'
import { api } from './lib/api'
import { useAsync } from './components/ui'
import Overview from './pages/Overview'
import Jobs from './pages/Jobs'
import Applications from './pages/Applications'
import Pipeline from './pages/Pipeline'
import Setup from './pages/Setup'
import Activity from './pages/Activity'
import Sources from './pages/Sources'
import Inbox from './pages/Inbox'

const PAGES = [
  { id: 'overview', label: 'Overview', Component: Overview },
  { id: 'jobs', label: 'Jobs', Component: Jobs },
  { id: 'sources', label: 'Job sources', Component: Sources },
  { id: 'applications', label: 'Applications', Component: Applications },
  { id: 'inbox', label: 'Inbox', Component: Inbox },
  { id: 'pipeline', label: 'Pipeline health', Component: Pipeline },
  { id: 'activity', label: 'Activity', Component: Activity },
  { id: 'setup', label: 'Setup', Component: Setup },
]

/** Persist the theme choice and stamp it on <html>, so the tokens'
 *  [data-theme] scope wins over the OS setting in both directions. */
function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('ca-theme') || 'system' } catch { return 'system' }
  })
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try { localStorage.setItem('ca-theme', theme) } catch { /* private mode */ }
  }, [theme])
  return [theme, setTheme]
}

export default function App() {
  const [page, setPage] = useState(() => {
    const hash = window.location.hash.replace('#', '')
    return PAGES.some((p) => p.id === hash) ? hash : 'overview'
  })
  const [theme, setTheme] = useTheme()

  useEffect(() => {
    const onHash = () => {
      const hash = window.location.hash.replace('#', '')
      if (PAGES.some((p) => p.id === hash)) setPage(hash)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = (id) => { window.location.hash = id; setPage(id) }

  // Badges that tell the user where attention is needed, refreshed in the background.
  const stats = useAsync(() => api.stats(), [], { poll: 30000 })
  const followups = useAsync(() => api.followups(), [], { poll: 60000 })
  const overdue = (followups.data || []).filter((f) => f.overdue).length

  const sources = useAsync(() => api.sources(), [], { poll: 120000 })
  const activeSources = (sources.data || []).filter((s) => s.active).length

  const badges = {
    applications: stats.data?.applications || null,
    pipeline: overdue || null,
    sources: activeSources || null,
  }

  const Current = PAGES.find((p) => p.id === page)?.Component || Overview

  return (
    <div className="app">
      <nav className="sidebar" aria-label="Sections">
        <div className="brand">
          <b>Career Agent</b>
          <div>Find → Prep → Apply → Track</div>
        </div>
        {PAGES.map((p) => (
          <button key={p.id} className="navlink" aria-current={page === p.id ? 'page' : undefined}
                  onClick={() => go(p.id)}>
            <span>{p.label}</span>
            {badges[p.id] ? <span className="pill">{badges[p.id]}</span> : null}
          </button>
        ))}
        <div style={{ marginTop: 'auto', paddingTop: 14 }}>
          <label htmlFor="theme">Theme</label>
          <select id="theme" value={theme} onChange={(e) => setTheme(e.target.value)}>
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
      </nav>
      <main className="content">
        <Current onNavigate={go} />
      </main>
    </div>
  )
}
