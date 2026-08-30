import { useState } from 'react'
import { api } from '../lib/api'
import { Action, Banner, Empty, Field, useAsync } from '../components/ui'
import { StatTile } from '../components/Charts'
import { timeAgo } from '../lib/format'

/** Market-wide sources: discovery that needs no watchlist, so genuinely new
 *  postings arrive on their own rather than only for companies you named. */
export default function Sources() {
  const sources = useAsync(() => api.sources(), [])
  const fresh = useAsync(() => api.freshness(), [])
  const [sample, setSample] = useState(null)
  const [days, setDays] = useState(null)

  const rows = sources.data || []
  const active = rows.filter((s) => s.active)
  const freshDays = days ?? fresh.data?.fresh_days ?? 30

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Job sources</h1>
          <p className="sub">
            These pull newly-posted jobs across the whole market against your keywords —
            no company list needed.
          </p>
        </div>
        <div className="btn-row">
          <Action className="btn primary" onClick={() => api.scanSources()} onDone={sources.reload}>
            Pull fresh jobs now
          </Action>
        </div>
      </div>

      <div className="grid k3">
        <StatTile label="Sources on" value={`${active.length} / ${rows.length}`}
                  foot="Enabled for every scan" />
        <StatTile label="Found last run" value={active.reduce((n, s) => n + (s.last_count || 0), 0)}
                  foot="Across enabled sources" />
        <StatTile label="Freshness cutoff" value={freshDays ? `${freshDays}d` : 'Off'}
                  foot={freshDays ? 'Older postings skipped' : 'Keeping everything'} />
      </div>

      <div className="card">
        <h3>Only keep postings newer than</h3>
        <p className="small muted">
          A feed that publishes no date is always kept — dropping undated rows would
          silently discard whole sources.
        </p>
        <div className="filter-row">
          <div className="field">
            <select value={freshDays} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={0}>No cutoff</option>
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </div>
          <Action className="btn" onClick={() => api.setFreshness(freshDays)}
                  onDone={fresh.reload}>
            Save
          </Action>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Available sources</h2>
            <p className="sub">{rows.length} sources. Turn on the ones that match your market.</p>
          </div>
        </div>
        {sources.error && <Banner kind="error">{sources.error}</Banner>}
        {!rows.length ? <Empty>Loading sources…</Empty> : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Source</th><th>Coverage</th><th>Last run</th>
                  <th className="num">Found</th><th>Status</th><th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className={s.active ? undefined : 'stale'}>
                    <td><b>{s.label}</b></td>
                    <td className="small muted">{s.coverage}</td>
                    <td className="small muted">{s.last_run ? timeAgo(s.last_run) : 'Never'}</td>
                    <td className="num">{s.last_count || 0}</td>
                    <td className="small">
                      {s.last_error
                        ? <span style={{ color: 'var(--status-critical)' }}>{s.last_error.slice(0, 60)}</span>
                        : <span className="muted">{s.active ? 'On' : 'Off'}</span>}
                    </td>
                    <td>
                      <div className="btn-row">
                        <Action className="btn small" onClick={() => api.toggleSource(s.id)}
                                onDone={sources.reload}>
                          {s.active ? 'Turn off' : 'Turn on'}
                        </Action>
                        <Action className="btn small"
                                onClick={async () => setSample({ id: s.id, ...(await api.testSource(s.id)) })}>
                          Test
                        </Action>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {sample && (
        <div className="card">
          <div className="card-head">
            <div>
              <h2>Sample from {sample.id}</h2>
              <p className="sub">{sample.count} rows fetched — nothing was saved.</p>
            </div>
            <button className="btn small" onClick={() => setSample(null)}>Close</button>
          </div>
          {!sample.sample?.length ? <Empty>This source returned nothing.</Empty> : (
            <div className="table-scroll">
              <table className="table">
                <thead><tr><th>Role</th><th>Company</th><th>Location</th><th>Posted</th></tr></thead>
                <tbody>
                  {sample.sample.map((j, i) => (
                    <tr key={i}>
                      <td><a href={j.url} target="_blank" rel="noreferrer">{j.title}</a></td>
                      <td>{j.company || '—'}</td>
                      <td className="small">{j.location || '—'}</td>
                      <td className="small muted">{j.posted_at ? timeAgo(j.posted_at) : 'undated'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}
