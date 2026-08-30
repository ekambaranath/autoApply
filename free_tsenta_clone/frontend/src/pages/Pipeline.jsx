import { api } from '../lib/api'
import { Action, Banner, Empty, StatusPill, useAsync } from '../components/ui'
import { BarChart, ChartCard, DataTable, StatTile } from '../components/Charts'
import { dateOnly, humanStatus } from '../lib/format'

/** Follow-ups, re-listings and per-channel advance rates: the questions a
 *  tracker can answer that a job list cannot. */
export default function Pipeline() {
  const followups = useAsync(() => api.followups(), [], { poll: 60000 })
  const reposts = useAsync(() => api.reposts(), [])
  const channels = useAsync(() => api.channels(), [])

  const due = followups.data || []
  const overdue = due.filter((f) => f.overdue)
  const upcoming = due.filter((f) => !f.overdue)
  const clusters = reposts.data || []
  const ch = channels.data?.channels || []
  const stages = channels.data?.stages || []

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pipeline health</h1>
          <p className="sub">Where applications are stalling, and which are due a nudge.</p>
        </div>
      </div>

      <div className="grid k3">
        <StatTile label="Overdue follow-ups" value={overdue.length}
                  foot={overdue.length ? 'Chase these first' : 'Nothing overdue'}
                  tone={overdue.length ? 'var(--status-warning)' : undefined} />
        <StatTile label="Due soon" value={upcoming.length} foot="Within the cadence" />
        <StatTile label="Re-listed roles" value={clusters.length}
                  foot="Possible ghost jobs" />
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Follow-up cadence</h2>
            <p className="sub">
              A first nudge 7 days after applying, then one more; replies get a next-day answer and
              interviews a thank-you. Logging a follow-up restarts that application's clock.
            </p>
          </div>
        </div>
        {followups.error && <Banner kind="error">{followups.error}</Banner>}
        {!due.length ? (
          <Empty>No live applications to chase. Follow-ups start once something is submitted.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th><th>Company</th><th>Status</th><th>Due</th>
                  <th className="num">Sent</th><th>Why</th><th></th>
                </tr>
              </thead>
              <tbody>
                {due.map((f) => (
                  <tr key={f.application_id}>
                    <td><b>{f.title}</b></td>
                    <td>{f.company || '—'}</td>
                    <td><StatusPill status={f.status} /></td>
                    <td className="small">
                      {f.overdue ? (
                        <span style={{ color: 'var(--status-warning)' }}>
                          {f.days_overdue}d overdue
                        </span>
                      ) : (
                        <span className="muted">in {f.days_until_due}d · {dateOnly(f.due_date)}</span>
                      )}
                    </td>
                    <td className="num">{f.followups_sent}</td>
                    <td className="small muted">{f.reason}</td>
                    <td>
                      <Action className="btn small" onClick={() => api.logFollowup(f.application_id)}
                              onDone={followups.reload}>
                        Mark sent
                      </Action>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid k2" style={{ marginTop: 14 }}>
        <ChartCard
          title="Advance rate by ATS"
          subtitle="Of what you sent through each channel, how much drew a reply"
          stale={channels.stale}
          table={<DataTable
            columns={[
              { key: 'channel', label: 'Channel' },
              { key: 'applications', label: 'Sent', num: true },
              { key: 'advanced', label: 'Advanced', num: true },
              { key: 'advance_rate', label: 'Rate %', num: true },
            ]}
            rows={ch} />}
        >
          {ch.length
            ? <BarChart data={ch} labelKey="channel" valueKey="advance_rate" />
            : <Empty>No submitted applications yet.</Empty>}
        </ChartCard>

        <ChartCard
          title="Where applications sit"
          subtitle="The stage distribution across your pipeline"
          stale={channels.stale}
          table={<DataTable
            columns={[
              { key: 'status', label: 'Status', render: (r) => humanStatus(r.status) },
              { key: 'count', label: 'Count', num: true },
              { key: 'share', label: 'Share %', num: true },
            ]}
            rows={stages} />}
        >
          {stages.length
            ? <BarChart data={stages.map((s) => ({ label: humanStatus(s.status), count: s.count }))} />
            : <Empty>No applications yet.</Empty>}
        </ChartCard>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Re-listed roles</h2>
            <p className="sub">
              The same role posted again at a fresh URL. Two listings that first appeared on the same
              day are concurrent requisitions, not a re-listing, so they are excluded.
            </p>
          </div>
        </div>
        {!clusters.length ? (
          <Empty>No re-listings detected in the last 90 days.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Company</th><th>Role</th><th className="num">Listings</th>
                  <th>First seen</th><th>Last seen</th><th className="num">Span</th>
                </tr>
              </thead>
              <tbody>
                {clusters.map((c, i) => (
                  <tr key={i}>
                    <td>{c.company || '—'}</td>
                    <td><b>{c.role}</b></td>
                    <td className="num">{c.repost_count}</td>
                    <td className="small muted">{c.first_seen}</td>
                    <td className="small muted">{c.last_seen}</td>
                    <td className="num">{c.days_span}d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
