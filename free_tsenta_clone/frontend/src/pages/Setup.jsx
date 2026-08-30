import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Action, Banner, Empty, Field, Tabs, useAsync } from '../components/ui'

function ProfileForm() {
  const profile = useAsync(() => api.profile(), [])
  const resume = useAsync(() => api.resumeText(), [])
  const [form, setForm] = useState({})
  const [file, setFile] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => { if (profile.data) setForm(profile.data) }, [profile.data])
  const set = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setSaved(false) }
  const hasResume = Boolean(resume.data?.resume_file)

  const save = async () => {
    const fd = new FormData()
    for (const k of ['name', 'email', 'phone', 'location', 'linkedin', 'github']) {
      fd.append(k, form[k] || '')
    }
    if (file) fd.append('resume', file)
    await api.saveProfile(fd)
    setSaved(true)
    setFile(null)
    profile.reload()
    resume.reload()
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Your details</h2>
          <p className="sub">Used to fill application forms and to score how well jobs match you.</p>
        </div>
      </div>
      {saved && <Banner kind="good">Profile saved.</Banner>}
      <div className="grid k2">
        <Field label="Full name"><input value={form.name || ''} onChange={set('name')} /></Field>
        <Field label="Email"><input type="email" value={form.email || ''} onChange={set('email')} /></Field>
        <Field label="Phone"><input value={form.phone || ''} onChange={set('phone')} /></Field>
        <Field label="Location"><input value={form.location || ''} onChange={set('location')} /></Field>
        <Field label="LinkedIn"><input value={form.linkedin || ''} onChange={set('linkedin')} /></Field>
        <Field label="GitHub"><input value={form.github || ''} onChange={set('github')} /></Field>
      </div>
      <Field label="Resume" hint={hasResume ? 'already on file — upload only to replace it' : 'PDF, DOCX or TXT (required)'}>
        <input type="file" accept=".pdf,.docx,.txt" onChange={(e) => setFile(e.target.files[0] || null)} />
      </Field>
      {hasResume && (
        <p className="small muted">
          {resume.data.resume_text.length.toLocaleString()} characters extracted from your resume.
        </p>
      )}
      <div className="btn-row" style={{ marginTop: 10 }}>
        <Action className="btn primary" onClick={save}>Save profile</Action>
      </div>
    </div>
  )
}

function PreferencesForm() {
  const prefs = useAsync(() => api.preferences(), [])
  const [form, setForm] = useState({})
  const [saved, setSaved] = useState(false)
  const [probe, setProbe] = useState('Senior Python Engineer\nMarketing Intern\nInternal Tools Lead')
  const [preview, setPreview] = useState(null)

  useEffect(() => { if (prefs.data) setForm(prefs.data) }, [prefs.data])
  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm({ ...form, [k]: v }); setSaved(false)
  }

  const save = async () => {
    await api.savePreferences({
      roles: form.roles || '', locations: form.locations || '', remote: form.remote || 'Any',
      min_salary: Number(form.min_salary) || 0, max_salary: Number(form.max_salary) || 0,
      work_auth: form.work_auth || '', sponsorship: form.sponsorship || 'Any',
      excluded_companies: form.excluded_companies || '', keywords: form.keywords || '',
      excluded_titles: form.excluded_titles || '',
      auto_apply: Boolean(form.auto_apply), review_required: form.review_required !== false,
    })
    setSaved(true)
    prefs.reload()
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>What you are looking for</h2>
          <p className="sub">These steer match scoring and which postings a scan keeps.</p>
        </div>
      </div>
      {saved && <Banner kind="good">Preferences saved.</Banner>}
      <div className="grid k2">
        <Field label="Target roles"><input value={form.roles || ''} onChange={set('roles')}
                placeholder="backend engineer, platform engineer" /></Field>
        <Field label="Locations"><input value={form.locations || ''} onChange={set('locations')}
                placeholder="Berlin, Remote EU" /></Field>
        <Field label="Remote preference">
          <select value={form.remote || 'Any'} onChange={set('remote')}>
            <option>Any</option><option>Remote</option><option>Hybrid</option><option>Onsite</option>
          </select>
        </Field>
        <Field label="Sponsorship">
          <select value={form.sponsorship || 'Any'} onChange={set('sponsorship')}>
            <option>Any</option><option>Required</option><option>Not required</option>
          </select>
        </Field>
        <Field label="Minimum salary">
          <input type="number" value={form.min_salary || 0} onChange={set('min_salary')} />
        </Field>
        <Field label="Work authorization">
          <input value={form.work_auth || ''} onChange={set('work_auth')} placeholder="EU citizen" />
        </Field>
      </div>

      <Field label="Title keywords to keep"
             hint="blank keeps everything · word:vp exact · stem:agent prefix · a + b requires both">
        <input value={form.keywords || ''} onChange={set('keywords')}
               placeholder="python, stem:agent, director + engineering" />
      </Field>
      <Field label="Title keywords to reject" hint="a veto, applied after the keep list">
        <input value={form.excluded_titles || ''} onChange={set('excluded_titles')}
               placeholder="word:intern, sales, recruiter" />
      </Field>
      <Field label="Companies to exclude">
        <input value={form.excluded_companies || ''} onChange={set('excluded_companies')} />
      </Field>

      <div className="card" style={{ background: 'var(--page)' }}>
        <h3>Test the title filter</h3>
        <p className="small muted">
          A filter that silently drops everything is the failure worth catching before a scan —
          the run summary only reports one count, which cannot tell a tuned filter from a leaking one.
        </p>
        <textarea rows={4} value={probe} onChange={(e) => setProbe(e.target.value)}
                  placeholder="One job title per line" />
        <div className="btn-row" style={{ marginTop: 8 }}>
          <Action className="btn small"
                  onClick={async () => setPreview(await api.testFilter(
                    probe.split('\n').map((t) => t.trim()).filter(Boolean),
                    form.keywords, form.excluded_titles))}>
            Preview
          </Action>
        </div>
        {preview && (
          <table className="table" style={{ marginTop: 10 }}>
            <thead><tr><th>Title</th><th>Kept?</th></tr></thead>
            <tbody>
              {preview.map((p, i) => (
                <tr key={i}>
                  <td>{p.title}</td>
                  <td style={{ color: p.kept ? 'var(--status-good)' : 'var(--status-critical)' }}>
                    {p.kept ? 'Kept' : 'Filtered out'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="btn-row" style={{ marginTop: 12 }}>
        <Action className="btn primary" onClick={save}>Save preferences</Action>
      </div>
    </div>
  )
}

function Watchlist() {
  const list = useAsync(() => api.watchlist(), [])
  const providers = useAsync(() => api.providers(), [])
  const [form, setForm] = useState({ company: '', url: '', platform: 'auto', slug: '' })
  const [detected, setDetected] = useState(null)

  const onUrlBlur = async () => {
    if (!form.url) return setDetected(null)
    try {
      const d = await api.detectProvider(form.url)
      setDetected(d)
    } catch { setDetected(null) }
  }

  return (
    <>
      <div className="card">
        <div className="card-head">
          <div>
            <h2>Add a company</h2>
            <p className="sub">
              Paste a careers URL — the board and its slug are detected automatically.
              Anything unrecognised falls back to a best-effort crawl.
            </p>
          </div>
        </div>
        <div className="grid k2">
          <Field label="Company"><input value={form.company}
                  onChange={(e) => setForm({ ...form, company: e.target.value })} /></Field>
          <Field label="Careers URL">
            <input value={form.url} onBlur={onUrlBlur}
                   onChange={(e) => setForm({ ...form, url: e.target.value })}
                   placeholder="https://jobs.ashbyhq.com/acme" />
          </Field>
        </div>
        {detected && (
          <Banner kind={detected.provider ? 'good' : 'warning'}>
            {detected.provider
              ? <>Detected <b>{detected.provider}</b>{detected.slug ? <> · board <b>{detected.slug}</b></> : ''}.</>
              : <>No known ATS behind that URL — it will be crawled generically, which finds less.</>}
          </Banner>
        )}
        <div className="btn-row" style={{ marginTop: 10 }}>
          <Action className="btn primary" disabled={!form.company || !form.url}
                  onClick={() => api.addWatch(form)}
                  onDone={() => { setForm({ company: '', url: '', platform: 'auto', slug: '' }); setDetected(null); list.reload() }}>
            Add to watchlist
          </Action>
          <Action className="btn" onClick={() => api.scan()} onDone={list.reload}>Scan now</Action>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          Supported boards: {(providers.data || []).map((p) => p.id).join(', ') || '…'}
        </p>
      </div>

      <div className="card">
        <h2>Watchlist</h2>
        {!list.data?.length ? (
          <Empty>No companies yet. Add one above to give the scanner something to check.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr><th>Company</th><th>Board</th><th>Slug</th><th>Active</th><th></th></tr>
              </thead>
              <tbody>
                {list.data.map((w) => (
                  <tr key={w.id} className={w.active ? undefined : 'stale'}>
                    <td><b>{w.company}</b></td>
                    <td><span className="pill">{w.platform}</span></td>
                    <td className="small mono">{w.slug || '—'}</td>
                    <td className="small">{w.active ? 'Yes' : 'Paused'}</td>
                    <td>
                      <div className="btn-row">
                        <Action className="btn small" onClick={() => api.toggleWatch(w.id)} onDone={list.reload}>
                          {w.active ? 'Pause' : 'Resume'}
                        </Action>
                        <Action className="btn small danger" confirm={`Remove ${w.company} from the watchlist?`}
                                onClick={() => api.deleteWatch(w.id)} onDone={list.reload}>
                          Remove
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
    </>
  )
}


function ModelPanel() {
  const info = useAsync(() => api.llm(), [])
  const [result, setResult] = useState(null)
  const cfg = info.data || {}
  const isOllama = cfg.provider === 'ollama'

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>AI model</h2>
          <p className="sub">Used to tailor your resume, write cover letters and answer screening questions.</p>
        </div>
        <Action className="btn primary" onClick={async () => setResult(await api.testLlm())}>
          Test the model
        </Action>
      </div>

      <div className="grid k2">
        <Field label="Provider"><input value={cfg.provider || ''} readOnly /></Field>
        <Field label="Model"><input value={cfg.model || ''} readOnly /></Field>
        <Field label="Endpoint"><input value={cfg.base_url || ''} readOnly /></Field>
        <Field label="Timeout"><input value={`${cfg.timeout || 0}s`} readOnly /></Field>
      </div>

      {!isOllama && !cfg.has_key && (
        <Banner kind="error">LLM_API_KEY is not set - every request will fail.</Banner>
      )}

      {result && (result.ok ? (
        <Banner kind="good">
          Working - replied in {result.seconds}s
          {result.json_clean
            ? ' and returned clean JSON.'
            : '. Note: the reply was not clean JSON, so tailoring may fall back.'}
        </Banner>
      ) : (
        <Banner kind="error">
          <b>Failed after {result.seconds}s.</b> {result.error}
        </Banner>
      ))}

      <h3>Switching to a hosted model</h3>
      <p className="small muted">
        Set these in your environment and restart. Nothing is stored in the database.
      </p>
      <pre className="mono diff-box" style={{ padding: 12 }}>{`LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-...
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
LLM_TIMEOUT=600`}</pre>
      <p className="small muted">
        Free tiers are served at low priority, so a full tailored resume can take minutes -
        that is why the timeout defaults to 600s. Free providers may also train on what you
        send, and every request includes your name, email and phone.
      </p>
    </div>
  )
}

export default function Setup() {
  const [tab, setTab] = useState('profile')
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Setup</h1>
          <p className="sub">Everything the agent needs to know before it goes to work.</p>
        </div>
      </div>
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: 'profile', label: 'Profile' },
        { id: 'prefs', label: 'Preferences' },
        { id: 'watch', label: 'Watchlist' },
        { id: 'model', label: 'AI model' },
      ]} />
      {tab === 'profile' && <ProfileForm />}
      {tab === 'prefs' && <PreferencesForm />}
      {tab === 'watch' && <Watchlist />}
      {tab === 'model' && <ModelPanel />}
    </>
  )
}
