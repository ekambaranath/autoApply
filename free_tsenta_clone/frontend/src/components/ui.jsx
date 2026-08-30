import { useCallback, useEffect, useRef, useState } from 'react'
import { statusTone, TONE_VAR, humanStatus } from '../lib/format'

/** Status always pairs a colored dot with its label — never color alone. */
export function StatusPill({ status, children }) {
  const tone = TONE_VAR[statusTone(status)]
  return (
    <span className="pill">
      <span className="dot" style={{ background: tone }} />
      {children || humanStatus(status)}
    </span>
  )
}

export function Banner({ kind = 'warning', children }) {
  return <div className={`banner ${kind === 'error' ? 'error' : kind === 'good' ? 'good' : ''}`}>{children}</div>
}

export function Empty({ children }) {
  return <p className="empty">{children}</p>
}

export function Field({ label, hint, children }) {
  return (
    <div className="field">
      <label>{label}{hint && <span className="muted"> — {hint}</span>}</label>
      {children}
    </div>
  )
}

/**
 * Load data from the API, with an explicit stale flag during refetch.
 * Holding the previous render at reduced opacity avoids a skeleton flash and
 * the layout jump that comes with it.
 */
export function useAsync(fn, deps = [], { poll = 0 } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true, stale: false })
  const mounted = useRef(true)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const run = useCallback(async (quiet = false) => {
    setState((s) => (s.data == null ? { ...s, loading: true } : { ...s, stale: !quiet }))
    try {
      const data = await fnRef.current()
      if (mounted.current) setState({ data, error: null, loading: false, stale: false })
    } catch (e) {
      if (mounted.current) setState((s) => ({ ...s, error: e.message, loading: false, stale: false }))
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    run()
    return () => { mounted.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    if (!poll) return undefined
    const id = setInterval(() => run(true), poll)
    return () => clearInterval(id)
  }, [poll, run])

  return { ...state, reload: run }
}

/** Inline action button that reports its own progress and failure. */
export function Action({ onClick, children, className = 'btn', confirm, disabled, onDone }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  return (
    <>
      <button className={className} disabled={busy || disabled}
              onClick={async () => {
                if (confirm && !window.confirm(confirm)) return
                setBusy(true); setErr(null)
                try {
                  await onClick()
                  onDone?.()
                } catch (e) { setErr(e.message) } finally { setBusy(false) }
              }}>
        {busy ? 'Working…' : children}
      </button>
      {err && <span className="small" style={{ color: 'var(--status-critical)', marginLeft: 8 }}>{err}</span>}
    </>
  )
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" className="tab" aria-selected={active === t.id}
                onClick={() => onChange(t.id)}>
          {t.label}{t.badge != null && <span className="pill" style={{ marginLeft: 6 }}>{t.badge}</span>}
        </button>
      ))}
    </div>
  )
}
