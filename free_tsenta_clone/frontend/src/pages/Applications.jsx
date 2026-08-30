import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { Action, Banner, Empty, StatusPill, Tabs, useAsync } from '../components/ui'
import { diffLines, humanStatus, timeAgo } from '../lib/format'

/** Line-level diff of the generated resume against the one on file, so an
 *  edit can be reviewed rather than taken on trust. */
function ResumeDiff({ before, after }) {
  const lines = useMemo(() => diffLines(before, after), [before, after])
  const changed = lines.filter((l) => l.type !== 'same').length
  if (!changed) return <p className="small muted">No changes from your original resume.</p>
  return (
    <>
      <p className="small muted" style={{ marginBottom: 8 }}>
        {lines.filter((l) => l.type === 'add').length} lines added,{' '}
        {lines.filter((l) => l.type === 'del').length} removed.
      </p>
      <div className="diff-box">
        {lines.map((l, i) => (
          <div key={i}
               className={`diff-line ${l.type === 'add' ? 'diff-add' : l.type === 'del' ? 'diff-del' : ''}`}>
            <span className="muted" style={{ userSelect: 'none' }}>
              {l.type === 'add' ? '+ ' : l.type === 'del' ? '− ' : '  '}
            </span>
            {l.text || ' '}
          </div>
        ))}
      </div>
    </>
  )
}

function AnswersEditor({ answers, onChange }) {
  const keys = Object.keys(answers || {})
  if (!keys.length) return <p className="small muted">No screening answers were generated.</p>
  return (
    <div className="stack">
      {keys.map((k) => {
        const pending = answers[k] === 'NEEDS_USER_INPUT'
        return (
          <div key={k}>
            <label htmlFor={`a-${k}`}>
              {k.replace(/_/g, ' ')}
              {pending && <span style={{ color: 'var(--status-warning)' }}> · needs your answer</span>}
            </label>
            <input id={`a-${k}`} value={pending ? '' : answers[k]}
                   placeholder={pending ? 'The agent will not guess this — type your answer' : ''}
                   style={pending ? { borderColor: 'var(--status-warning)' } : undefined}
                   onChange={(e) => onChange({ ...answers, [k]: e.target.value })} />
          </div>
        )
      })}
    </div>
  )
}

function Detail({ id, onChanged, onClose }) {
  const detail = useAsync(() => api.application(id), [id])
  const [tab, setTab] = useState('resume')
  const [draft, setDraft] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (detail.data) {
      setDraft({
        tailored_resume: detail.data.tailored_resume || '',
        cover_letter: detail.data.cover_letter || '',
        answers: detail.data.answers || {},
      })
    }
  }, [detail.data])

  if (detail.loading || !draft) return <div className="card"><p className="empty">Loading application…</p></div>
  if (detail.error) return <div className="card"><Banner kind="error">{detail.error}</Banner></div>

  const d = detail.data
  const pending = Object.entries(draft.answers).filter(([, v]) => v === 'NEEDS_USER_INPUT' || !String(v).trim())
  const changeLog = d.receipt?.change_log || []
  const locked = d.status === 'SUBMITTED'

  const save = async () => {
    await api.updateApplication(id, draft)
    setSaved(true)
    detail.reload()
    onChanged?.()
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>{d.title}</h2>
          <p className="sub">
            {d.company || 'Unknown company'} · <StatusPill status={d.status} /> · match {Math.round(d.match_score)}%
          </p>
        </div>
        <div className="btn-row">
          <a className="btn small" href={d.url} target="_blank" rel="noreferrer">Posting</a>
          <button className="btn small" onClick={onClose}>Close</button>
        </div>
      </div>

      {pending.length > 0 && (
        <Banner>
          {pending.length} screening answer{pending.length === 1 ? '' : 's'} still need you.
          The agent marks unknown personal facts <b>NEEDS_USER_INPUT</b> rather than inventing them,
          and will not submit until they are filled in.
        </Banner>
      )}
      {d.status === 'SECURITY_CHALLENGE' && (
        <Banner kind="error">
          The run stopped at a CAPTCHA, MFA or OTP challenge. Finish this one in your own browser —
          the agent will not attempt to bypass security controls.
        </Banner>
      )}
      {saved && <Banner kind="good">Saved.</Banner>}

      <Tabs
        active={tab} onChange={setTab}
        tabs={[
          { id: 'resume', label: 'Resume' },
          { id: 'letter', label: 'Cover letter' },
          { id: 'answers', label: 'Answers', badge: pending.length || null },
          { id: 'receipt', label: 'Receipt' },
          { id: 'events', label: 'History', badge: d.events?.length || null },
        ]}
      />

      {tab === 'resume' && (
        <>
          {changeLog.length > 0 && (
            <>
              <h3>What the agent changed</h3>
              <ul className="small" style={{ paddingLeft: 18 }}>
                {changeLog.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </>
          )}
          <h3>Diff against your resume on file</h3>
          <ResumeDiff before={d.original_resume} after={draft.tailored_resume} />
          <h3 style={{ marginTop: 14 }}>Edit</h3>
          <textarea rows={14} value={draft.tailored_resume} disabled={locked}
                    onChange={(e) => setDraft({ ...draft, tailored_resume: e.target.value })} />
        </>
      )}

      {tab === 'letter' && (
        <textarea rows={16} value={draft.cover_letter} disabled={locked}
                  onChange={(e) => setDraft({ ...draft, cover_letter: e.target.value })} />
      )}

      {tab === 'answers' && (
        <AnswersEditor answers={draft.answers}
                       onChange={(answers) => setDraft({ ...draft, answers })} />
      )}

      {tab === 'receipt' && (
        <>
          <pre className="mono diff-box" style={{ padding: 12, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(d.receipt, null, 2)}
          </pre>
          {d.has_screenshot && (
            <>
              <h3 style={{ marginTop: 14 }}>Form as the agent left it</h3>
              <img src={`/api/applications/${id}/screenshot`} alt="Screenshot of the filled application form"
                   style={{ width: '100%', borderRadius: 8, border: '1px solid var(--border)' }} />
            </>
          )}
        </>
      )}

      {tab === 'events' && (
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th>When</th><th>Event</th><th>Detail</th></tr></thead>
            <tbody>
              {(d.events || []).map((e) => (
                <tr key={e.id}>
                  <td className="small muted">{timeAgo(e.created_at)}</td>
                  <td><StatusPill status={e.event_type} /></td>
                  <td className="small mono" style={{ maxWidth: 420, wordBreak: 'break-word' }}>
                    {JSON.stringify(e.payload).slice(0, 300)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
        {!locked && <Action className="btn" onClick={save}>Save changes</Action>}
        {d.status === 'READY_FOR_REVIEW' && (
          <Action className="btn primary" disabled={pending.length > 0}
                  onClick={async () => { await save(); await api.approve(id) }}
                  onDone={() => { detail.reload(); onChanged?.() }}>
            Approve
          </Action>
        )}
        {['APPROVED', 'READY_TO_SUBMIT', 'SECURITY_CHALLENGE', 'ERROR'].includes(d.status) && (
          <>
            <Action className="btn primary" onClick={() => api.run(id, false)}
                    onDone={() => { detail.reload(); onChanged?.() }}>
              Fill the form (no submit)
            </Action>
            <Action className="btn"
                    confirm="Submit this application automatically? Review the resume, letter and answers first. The agent stops at any security challenge."
                    onClick={() => api.run(id, true)}
                    onDone={() => { detail.reload(); onChanged?.() }}>
              Fill and submit
            </Action>
          </>
        )}
        {d.status === 'SUBMITTED' && (
          <>
            <Action className="btn" onClick={() => api.logEvent(id, 'REPLIED', 'Employer replied')}
                    onDone={() => { detail.reload(); onChanged?.() }}>
              Log a reply
            </Action>
            <Action className="btn" onClick={() => api.logEvent(id, 'INTERVIEW', 'Interview scheduled')}
                    onDone={() => { detail.reload(); onChanged?.() }}>
              Log an interview
            </Action>
            <Action className="btn" onClick={() => api.logEvent(id, 'REJECTED', 'Rejected')}
                    onDone={() => { detail.reload(); onChanged?.() }}>
              Log a rejection
            </Action>
          </>
        )}
      </div>
    </div>
  )
}

export default function Applications() {
  const apps = useAsync(() => api.applications(), [], { poll: 20000 })
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState(null)

  const all = apps.data || []
  const statuses = useMemo(() => [...new Set(all.map((a) => a.status))].sort(), [all])
  const rows = status ? all.filter((a) => a.status === status) : all

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Applications</h1>
          <p className="sub">Review what the agent wrote before anything is sent.</p>
        </div>
      </div>

      <div className="card">
        <div className="filter-row">
          <div className="field">
            <label htmlFor="st">Status</label>
            <select id="st" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All ({all.length})</option>
              {statuses.map((s) => (
                <option key={s} value={s}>{humanStatus(s)} ({all.filter((a) => a.status === s).length})</option>
              ))}
            </select>
          </div>
        </div>

        {apps.error && <Banner kind="error">{apps.error}</Banner>}
        {!rows.length ? (
          <Empty>No applications yet — prepare one from the Jobs page.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th><th>Company</th><th>Status</th>
                  <th className="num">Match</th><th>Updated</th><th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td><b>{a.title}</b></td>
                    <td>{a.company || '—'}</td>
                    <td>
                      <StatusPill status={a.status} />
                      {a.needs_input?.length > 0 && (
                        <span className="pill" style={{ marginLeft: 6 }}>
                          {a.needs_input.length} to answer
                        </span>
                      )}
                    </td>
                    <td className="num">{Math.round(a.match_score)}%</td>
                    <td className="small muted">{timeAgo(a.updated_at)}</td>
                    <td>
                      <button className="btn small"
                              onClick={() => setOpen(open === a.id ? null : a.id)}>
                        {open === a.id ? 'Hide' : 'Review'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {open && (
        <div style={{ marginTop: 14 }}>
          <Detail id={open} onChanged={apps.reload} onClose={() => setOpen(null)} />
        </div>
      )}
    </>
  )
}
