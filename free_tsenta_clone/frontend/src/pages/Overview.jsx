import { api } from '../lib/api'
import { Action, Banner, useAsync } from '../components/ui'
import {
  BarChart, ChartCard, ColumnChart, DataTable, FunnelChart, LineChart, StatTile, fmt,
} from '../components/Charts'
import { compact, timeAgo } from '../lib/format'

export default function Overview({ onNavigate }) {
  const stats = useAsync(() => api.stats(), [], { poll: 30000 })
  const analytics = useAsync(() => api.analytics(), [], { poll: 30000 })
  const health = useAsync(() => api.health(), [])
  const followups = useAsync(() => api.followups(), [], { poll: 60000 })

  const a = analytics.data
  const s = stats.data || {}
  const overdue = (followups.data || []).filter((f) => f.overdue).length

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="sub">
            {health.data?.scheduler?.running
              ? `Background scanner runs every ${health.data.scheduler.interval_minutes} minutes.`
              : 'Background scanner is not running.'}
            {' '}It never bypasses CAPTCHA or MFA, and auto-submit stays opt-in.
          </p>
        </div>
        <div className="btn-row">
          <Action className="btn" onClick={() => api.scan()} onDone={() => { analytics.reload(); stats.reload() }}>
            Scan now
          </Action>
          <a className="btn" href="/api/export.csv">Export CSV</a>
        </div>
      </div>

      {stats.error && <Banner kind="error">Could not load stats: {stats.error}</Banner>}

      {s.needs_attention > 0 && (
        <Banner kind="error">
          {s.needs_attention} application{s.needs_attention === 1 ? '' : 's'} stopped on a security
          challenge or error and need you.{' '}
          <a href="#applications" onClick={() => onNavigate('applications')}>Review them</a>.
        </Banner>
      )}
      {overdue > 0 && (
        <Banner>
          {overdue} application{overdue === 1 ? ' is' : 's are'} overdue a follow-up.{' '}
          <a href="#pipeline" onClick={() => onNavigate('pipeline')}>Open pipeline health</a>.
        </Banner>
      )}

      <div className="grid k4" style={{ marginTop: 14 }}>
        <StatTile label="Jobs tracked" value={compact(s.jobs)} foot="Not dismissed" />
        <StatTile label="Strong matches" value={compact(s.matches)} foot="Score 70 or above" />
        <StatTile label="Submitted" value={compact(s.submitted)} foot="Applications sent" />
        <StatTile label="Responses" value={compact(s.responses)} foot="Replies, interviews, offers" />
      </div>

      <div className="grid k2" style={{ marginTop: 14 }}>
        <ChartCard
          title="Pipeline funnel"
          subtitle="Every job discovered, and how far it got"
          stale={analytics.stale}
          table={<DataTable
            columns={[{ key: 'stage', label: 'Stage' }, { key: 'count', label: 'Count', num: true }]}
            rows={a?.funnel || []} />}
        >
          {a ? <FunnelChart data={a.funnel} /> : <p className="empty">Loading…</p>}
        </ChartCard>

        <ChartCard
          title="Match score distribution"
          subtitle="How well tracked jobs fit your resume and preferences"
          stale={analytics.stale}
          table={<DataTable
            columns={[{ key: 'bin', label: 'Score' }, { key: 'count', label: 'Jobs', num: true }]}
            rows={a?.score_bins || []} />}
        >
          {a ? <ColumnChart data={a.score_bins} /> : <p className="empty">Loading…</p>}
        </ChartCard>
      </div>

      <ChartCard
        title="Discovery and applications over time"
        subtitle="Both series are counts, so they share one axis"
        stale={analytics.stale}
        table={<DataTable
          columns={[
            { key: 'date', label: 'Date' },
            { key: 'jobs', label: 'Jobs found', num: true },
            { key: 'applications', label: 'Applications', num: true },
          ]}
          rows={a?.timeline || []} />}
      >
        {a?.timeline?.length ? (
          <LineChart
            data={a.timeline}
            series={[
              { key: 'jobs', label: 'Jobs found', color: 'var(--series-1)' },
              { key: 'applications', label: 'Applications', color: 'var(--series-2)' },
            ]}
          />
        ) : <p className="empty">No activity yet — add companies to your watchlist and run a scan.</p>}
      </ChartCard>

      <div className="grid k2" style={{ marginTop: 14 }}>
        <ChartCard
          title="Top companies"
          subtitle="Where your tracked jobs come from"
          stale={analytics.stale}
          table={<DataTable
            columns={[{ key: 'label', label: 'Company' }, { key: 'count', label: 'Jobs', num: true }]}
            rows={a?.by_company || []} />}
        >
          {a ? <BarChart data={a.by_company} /> : null}
        </ChartCard>

        <ChartCard
          title="Applicant tracking systems"
          subtitle="Which ATS your pipeline runs through"
          stale={analytics.stale}
          table={<DataTable
            columns={[{ key: 'label', label: 'ATS' }, { key: 'count', label: 'Jobs', num: true }]}
            rows={a?.by_ats || []} />}
        >
          {a ? <BarChart data={a.by_ats} /> : null}
        </ChartCard>
      </div>
    </>
  )
}
