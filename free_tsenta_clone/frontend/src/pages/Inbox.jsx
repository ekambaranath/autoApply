import { useState } from 'react'
import { api } from '../lib/api'
import { Action, Banner, Empty, StatusPill, useAsync } from '../components/ui'
import { StatTile } from '../components/Charts'
import { timeAgo } from '../lib/format'

/** Reading replies is what stops status tracking from being manual —
 *  the step that otherwise gets skipped. */
export default function Inbox() {
  const mail = useAsync(() => api.mailbox(), [])
  const [result, setResult] = useState(null)
  const cfg = mail.data || {}

  if (!cfg.configured) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1>Inbox</h1>
            <p className="sub">Read employer replies and advance application statuses automatically.</p>
          </div>
        </div>
        <div className="card">
          <Banner>Not connected yet.</Banner>
          <h3>Connect a mailbox</h3>
          <p className="small">
            Set these in your environment (or a <span className="mono">.env</span> file) and restart
            the server. Credentials are read from the environment and never stored in the database.
          </p>
          <pre className="mono diff-box" style={{ padding: 12 }}>{`MAIL_IMAP_HOST=imap.gmail.com
MAIL_IMAP_PORT=993
MAIL_USER=you@example.com
MAIL_PASSWORD=your-app-password
MAIL_FOLDER=INBOX`}</pre>
          <Banner kind="error">
            Use an <b>app-specific password</b>, not your account password. Gmail and Outlook
            both require one with 2FA enabled and will reject a normal password.
          </Banner>
        </div>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Inbox</h1>
          <p className="sub">
            {cfg.user} · {cfg.host} · last read {cfg.last_sync ? timeAgo(cfg.last_sync) : 'never'}
          </p>
        </div>
        <div className="btn-row">
          <Action className="btn" onClick={async () => setResult(await api.mailSync(true))}>
            Preview (no changes)
          </Action>
          <Action className="btn primary" onClick={async () => setResult(await api.mailSync(false))}
                  onDone={mail.reload}>
            Read and update
          </Action>
        </div>
      </div>

      {result && (
        <>
          <div className="grid k3">
            <StatTile label="Messages read" value={result.checked} foot="Bulk senders skipped" />
            <StatTile label="Statuses advanced" value={result.updated}
                      foot={result.updated ? 'Applications moved forward' : 'Nothing to change'} />
            <StatTile label="Unmatched"
                      value={result.messages.filter((m) => !m.application_id).length}
                      foot="Left alone rather than guessed" />
          </div>

          <div className="card">
            <h2>What it found</h2>
            {!result.messages.length ? (
              <Empty>No new mail in the window.</Empty>
            ) : (
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr><th>From</th><th>Subject</th><th>Read as</th><th>Matched</th><th>Applied</th></tr>
                  </thead>
                  <tbody>
                    {result.messages.map((m) => (
                      <tr key={m.uid}>
                        <td className="small truncate" style={{ maxWidth: 200 }}>{m.from}</td>
                        <td className="small" style={{ maxWidth: 280 }}>{m.subject}</td>
                        <td><StatusPill status={m.classified} /></td>
                        <td className="small">
                          {m.application_id
                            ? <>{m.company} — {m.title}</>
                            : <span className="muted">{m.reason || 'no match'}</span>}
                        </td>
                        <td className="small">
                          {m.applied
                            ? <span style={{ color: 'var(--status-good)' }}>Updated</span>
                            : <span className="muted">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      <div className="card">
        <h3>How it decides</h3>
        <ul className="small" style={{ paddingLeft: 18, color: 'var(--text-secondary)' }}>
          <li>Rejections are matched <b>before</b> interviews — a rejection often mentions the
            interview it is declining, and reading that as an invitation is the costliest mistake.</li>
          <li>An application never moves backwards, and never leaves a terminal state.</li>
          <li>Anything it cannot place is reported unmatched rather than guessed at.</li>
          <li>Bulk senders (no-reply, job alerts, newsletters) are skipped entirely.</li>
        </ul>
      </div>
    </>
  )
}
