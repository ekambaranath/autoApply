import { api } from '../lib/api'
import { Action, Banner, Empty, StatusPill, useAsync } from '../components/ui'
import { timeAgo } from '../lib/format'

function ScanRow({ item }) {
  const errors = (item.detail || []).filter((d) => d.error)
  const filtered = (item.detail || []).reduce((n, d) => n + (d.filtered_by_title || 0), 0)
  return (
    <>
      <b>Watchlist scan</b> ({item.trigger}) — {item.jobs_found} job
      {item.jobs_found === 1 ? '' : 's'} from {item.companies} compan
      {item.companies === 1 ? 'y' : 'ies'}
      {filtered > 0 && <span className="muted"> · {filtered} filtered out by title</span>}
      {errors.length > 0 && (
        <div className="small" style={{ color: 'var(--status-serious)', marginTop: 4 }}>
          {errors.map((e, i) => <div key={i}>{e.company}: {e.error}</div>)}
        </div>
      )}
    </>
  )
}

export default function Activity() {
  const feed = useAsync(() => api.activity(80), [], { poll: 15000 })
  const items = feed.data || []

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Activity</h1>
          <p className="sub">Everything the agent has done, newest first. Refreshes every 15 seconds.</p>
        </div>
        <div className="btn-row">
          <Action className="btn" onClick={() => api.scan()} onDone={feed.reload}>Scan now</Action>
          <button className="btn" onClick={() => feed.reload()}>Refresh</button>
        </div>
      </div>

      {feed.error && <Banner kind="error">{feed.error}</Banner>}

      <div className={`card ${feed.stale ? 'stale' : ''}`}>
        {!items.length ? (
          <Empty>Nothing has happened yet. Run a scan or prepare an application.</Empty>
        ) : (
          <div className="stack">
            {items.map((it) => (
              <div key={`${it.kind}-${it.id}`}
                   style={{ display: 'grid', gridTemplateColumns: '92px 1fr', gap: 12,
                            paddingBottom: 10, borderBottom: '1px solid var(--gridline)' }}>
                <div className="small muted" title={it.at}>{timeAgo(it.at)}</div>
                <div>
                  {it.kind === 'scan' ? <ScanRow item={it} /> : (
                    <>
                      <StatusPill status={it.type} />{' '}
                      {it.title ? <><b>{it.title}</b>{it.company ? ` at ${it.company}` : ''}</>
                                : <span className="muted">application {String(it.application_id).slice(0, 8)}</span>}
                      {it.payload?.note && <div className="small muted">{it.payload.note}</div>}
                      {it.payload?.change_log?.length > 0 && (
                        <ul className="small muted" style={{ paddingLeft: 18, margin: '4px 0 0' }}>
                          {it.payload.change_log.slice(0, 4).map((c, i) => <li key={i}>{c}</li>)}
                        </ul>
                      )}
                      {it.payload?.challenges?.length > 0 && (
                        <div className="small" style={{ color: 'var(--status-warning)' }}>
                          {it.payload.challenges.join(' ')}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
