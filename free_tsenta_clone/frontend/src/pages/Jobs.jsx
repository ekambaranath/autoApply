import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { Action, Banner, Empty, Field, StatusPill, useAsync } from '../components/ui'
import { Meter } from '../components/Charts'
import { TONE_VAR, hostOf, timeAgo } from '../lib/format'

const SEVERITY_TONE = { critical: 'critical', serious: 'serious', warning: 'warning', notice: 'neutral' }

function LegitimacyPanel({ jobId }) {
  const { data, loading, error } = useAsync(() => api.legitimacy(jobId), [jobId])
  if (loading) return <p className="small muted">Checking posting signals…</p>
  if (error) return <p className="small muted">Could not check posting: {error}</p>
  if (!data?.flags?.length) return <p className="small muted">No posting-quality concerns found.</p>
  return (
    <div className="stack">
      {data.flags.map((f) => (
        <div key={f.code} className="small" style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <span className="dot" style={{
            background: TONE_VAR[SEVERITY_TONE[f.severity]], width: 7, height: 7,
            borderRadius: '50%', marginTop: 6, flex: 'none',
          }} />
          <span><b>{f.severity}</b> — {f.text}</span>
        </div>
      ))}
      <p className="small muted">
        These are signals, not verdicts, and they are deliberately kept out of the match score:
        whether a posting is real is a different question from whether it suits you.
      </p>
    </div>
  )
}

function JobDetail({ job, onClose, onChanged }) {
  const detail = useAsync(() => api.job(job.id), [job.id])
  const d = detail.data || job
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="card-head">
        <div>
          <h2>{d.title}</h2>
          <p className="sub">{d.company || 'Unknown company'}{d.location ? ` · ${d.location}` : ''} · {d.ats}</p>
        </div>
        <button className="btn small" onClick={onClose}>Close</button>
      </div>

      <div className="grid k2">
        <div>
          <h3>Why this scored {Math.round(d.match_score)}%</h3>
          <Meter value={d.match_score} />
          <ul className="small" style={{ paddingLeft: 18, marginTop: 10 }}>
            {(d.match_reasons || []).map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
        <div>
          <h3>Posting signals</h3>
          <LegitimacyPanel jobId={d.id} />
        </div>
      </div>

      <h3 style={{ marginTop: 16 }}>Description</h3>
      <div className="diff-box" style={{ padding: 12, whiteSpace: 'pre-wrap', maxHeight: 300 }}>
        {d.description || 'No description captured.'}
      </div>

      <div className="btn-row" style={{ marginTop: 14 }}>
        <a className="btn" href={d.url} target="_blank" rel="noreferrer">Open posting</a>
        <Action className="btn primary" onClick={() => api.prepare(d.id)} onDone={onChanged}>
          Prepare application
        </Action>
        <Action className="btn" onClick={() => api.dismissJob(d.id, !d.dismissed)} onDone={onChanged}>
          {d.dismissed ? 'Restore' : 'Dismiss'}
        </Action>
      </div>
    </div>
  )
}

export default function Jobs({ onNavigate }) {
  const [includeDismissed, setIncludeDismissed] = useState(false)
  const jobs = useAsync(() => api.jobs(includeDismissed), [includeDismissed])
  const [selected, setSelected] = useState(null)
  const [q, setQ] = useState('')
  const [minScore, setMinScore] = useState(0)
  const [ats, setAts] = useState('')
  const [importUrl, setImportUrl] = useState('')

  const all = jobs.data || []
  const atsOptions = useMemo(
    () => [...new Set(all.map((j) => j.ats).filter(Boolean))].sort(), [all])

  // One filter row scoping the whole table, rather than per-column controls.
  const rows = useMemo(() => all.filter((j) => {
    if (minScore && (j.match_score || 0) < minScore) return false
    if (ats && j.ats !== ats) return false
    if (q) {
      const hay = `${j.title} ${j.company} ${j.location}`.toLowerCase()
      if (!hay.includes(q.toLowerCase())) return false
    }
    return true
  }), [all, q, minScore, ats])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Jobs</h1>
          <p className="sub">{rows.length} of {all.length} tracked jobs</p>
        </div>
        <div className="btn-row">
          <Action className="btn" onClick={() => api.rescore()} onDone={jobs.reload}>
            Re-score all
          </Action>
        </div>
      </div>

      <div className="card">
        <h3>Import a job by URL</h3>
        <div className="filter-row">
          <div className="field grow">
            <input value={importUrl} onChange={(e) => setImportUrl(e.target.value)}
                   placeholder="https://company.com/careers/engineer" />
          </div>
          <Action className="btn primary" disabled={!importUrl}
                  onClick={() => api.importUrl(importUrl)}
                  onDone={() => { setImportUrl(''); jobs.reload() }}>
            Import
          </Action>
        </div>
      </div>

      <div className="card">
        <div className="filter-row">
          <div className="field grow">
            <label htmlFor="q">Search</label>
            <input id="q" value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder="Title, company or location" />
          </div>
          <div className="field">
            <label htmlFor="score">Minimum score</label>
            <select id="score" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))}>
              <option value={0}>Any</option>
              <option value={50}>50+</option>
              <option value={70}>70+ (strong)</option>
              <option value={85}>85+</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="ats">ATS</label>
            <select id="ats" value={ats} onChange={(e) => setAts(e.target.value)}>
              <option value="">All</option>
              {atsOptions.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="dis">Dismissed</label>
            <select id="dis" value={String(includeDismissed)}
                    onChange={(e) => setIncludeDismissed(e.target.value === 'true')}>
              <option value="false">Hidden</option>
              <option value="true">Shown</option>
            </select>
          </div>
        </div>

        {jobs.error && <Banner kind="error">{jobs.error}</Banner>}
        {!rows.length ? (
          <Empty>
            {all.length
              ? 'No jobs match these filters.'
              : 'No jobs yet — add companies on the Setup page, then run a scan.'}
          </Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th><th>Company</th><th>Location</th><th>ATS</th>
                  <th className="num">Score</th><th>Found</th><th></th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 200).map((j) => (
                  <tr key={j.id} className={j.dismissed ? 'stale' : undefined}>
                    <td style={{ maxWidth: 300 }}>
                      <b>{j.title}</b>
                      <div className="small muted">{hostOf(j.url)}</div>
                    </td>
                    <td>{j.company || '—'}</td>
                    <td className="small">{j.location || '—'}</td>
                    <td><span className="pill">{j.ats}</span></td>
                    <td className="num">{Math.round(j.match_score)}%</td>
                    <td className="small muted">{timeAgo(j.created_at)}</td>
                    <td>
                      <button className="btn small"
                              onClick={() => setSelected(selected?.id === j.id ? null : j)}>
                        {selected?.id === j.id ? 'Hide' : 'Details'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > 200 && (
              <p className="small muted" style={{ marginTop: 10 }}>
                Showing the top 200 of {rows.length}. Narrow the filters to see more.
              </p>
            )}
          </div>
        )}
      </div>

      {selected && (
        <JobDetail job={selected} onClose={() => setSelected(null)}
                   onChanged={() => { jobs.reload(); setSelected(null); onNavigate?.('applications') }} />
      )}
    </>
  )
}
