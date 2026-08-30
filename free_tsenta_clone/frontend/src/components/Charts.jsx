import { useCallback, useId, useMemo, useState } from 'react'

/* Chart primitives, hand-rolled in SVG so the mark specs hold exactly:
   bars capped at 24px with a 4px rounded data-end squared at the baseline, 2px
   lines, >=8px markers ringed in the surface color, hairline solid gridlines,
   and a 2px surface gap between adjacent marks. Every color comes from a CSS
   token, so light/dark swap in one place and the chart body never holds a hex.
   Each chart ships a table-view twin: a tooltip may enhance, never gate. */

const AXIS = 'var(--text-muted)'
const GRID = 'var(--gridline)'

/* ------------------------------------------------------------- tooltip */
function useTooltip() {
  const [tip, setTip] = useState(null)
  const show = useCallback((e, content) => {
    const r = e.currentTarget.getBoundingClientRect()
    setTip({ content, x: r.left + r.width / 2, y: r.top })
  }, [])
  const hide = useCallback(() => setTip(null), [])
  const node = tip ? (
    <div className="chart-tooltip" role="status"
         style={{ left: tip.x, top: tip.y - 10, transform: 'translate(-50%,-100%)' }}>
      {tip.content}
    </div>
  ) : null
  return { show, hide, node }
}

const fmt = (n) => Number(n || 0).toLocaleString()

/**
 * Clean integer axis ticks.
 *
 * These axes count things, so a fractional midpoint is meaningless — and once
 * rounded for display it collides with its neighbour, printing "1, 1, 0" on a
 * max of 1. Picking an integer step first avoids both.
 */
function niceScale(value) {
  const v = Math.max(1, Math.ceil(value))
  if (v <= 5) return { max: v, ticks: Array.from({ length: v + 1 }, (_, i) => i) }
  const mag = 10 ** Math.floor(Math.log10(v))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => v / s <= 4) || mag * 10
  const max = Math.ceil(v / step) * step
  const ticks = []
  for (let t = 0; t <= max + 1e-9; t += step) ticks.push(Math.round(t))
  return { max, ticks: [...new Set(ticks)] }
}

/* ---------------------------------------------------------- chart card */
export function ChartCard({ title, subtitle, children, table, stale }) {
  const [showTable, setShowTable] = useState(false)
  const id = useId()
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="sub">{subtitle}</p>}
        </div>
        {table && (
          <button className="btn small" onClick={() => setShowTable((v) => !v)}
                  aria-expanded={showTable} aria-controls={id}>
            {showTable ? 'Chart' : 'Table'}
          </button>
        )}
      </div>
      <div id={id} className={stale ? 'stale' : undefined}>
        {showTable && table ? table : children}
      </div>
    </div>
  )
}

export function DataTable({ columns, rows }) {
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>{columns.map((c) => <th key={c.key} className={c.num ? 'num' : ''}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? 'num' : ''}>
                  {c.render ? c.render(r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ----------------------------------------------------------- stat tile */
export function StatTile({ label, value, foot, tone }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value" style={tone ? { color: tone } : undefined}>{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  )
}

/* --------------------------------------------------------- funnel bars */
/** Ordered stages, so the ordinal ramp is the right color job (not categorical,
 *  and not a value-ramp on nominal categories). Five stages, five ramp steps. */
export function FunnelChart({ data }) {
  const { show, hide, node } = useTooltip()
  const max = Math.max(1, ...data.map((d) => d.count))
  return (
    <div>
      {node}
      <div className="stack">
        {data.map((d, i) => {
          const pct = (d.count / max) * 100
          const prev = i > 0 ? data[i - 1].count : null
          const conv = prev ? Math.round((d.count / Math.max(1, prev)) * 100) : null
          return (
            <div key={d.stage}>
              <div className="row-between" style={{ marginBottom: 3 }}>
                <span className="small">{d.stage}</span>
                <span className="small muted">
                  {/* Direct-labeled: five stages is few enough that each value is the point. */}
                  <b style={{ color: 'var(--text-primary)' }}>{fmt(d.count)}</b>
                  {conv !== null && <> · {conv}% of previous</>}
                </span>
              </div>
              {/* The track is the surface; the fill is the mark. Height 14px is
                  under the 24px cap and leaves the band's remainder as air. */}
              <div style={{ background: 'var(--surface-2)', borderRadius: 4, height: 14 }}
                   tabIndex={0} role="img"
                   aria-label={`${d.stage}: ${d.count}`}
                   onMouseEnter={(e) => show(e, <><b>{d.stage}</b><br />{fmt(d.count)}{conv !== null && <> · {conv}% of previous stage</>}</>)}
                   onFocus={(e) => show(e, <><b>{d.stage}</b><br />{fmt(d.count)}</>)}
                   onMouseLeave={hide} onBlur={hide}>
                <div style={{
                  width: `${Math.max(d.count ? 1.5 : 0, pct)}%`, height: '100%',
                  background: `var(--ord-${i + 1})`,
                  /* Square at the baseline, 4px rounded at the data end. */
                  borderRadius: '0 4px 4px 0',
                }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------ horizontal bars */
/** One series, one color (slot 1). A ramp here would double-encode length as
 *  hue on categories that have no natural order. */
export function BarChart({ data, labelKey = 'label', valueKey = 'count', height = 22 }) {
  const { show, hide, node } = useTooltip()
  const max = Math.max(1, ...data.map((d) => d[valueKey]))
  if (!data.length) return <p className="empty">No data yet.</p>
  return (
    <div>
      {node}
      {/* 10px row gap keeps well clear of the 2px minimum between adjacent marks. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {data.map((d) => (
          <div key={d[labelKey]} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 52px', gap: 10, alignItems: 'center' }}
               tabIndex={0} role="img" aria-label={`${d[labelKey]}: ${d[valueKey]}`}
               onMouseEnter={(e) => show(e, <><b>{d[labelKey]}</b><br />{fmt(d[valueKey])}</>)}
               onFocus={(e) => show(e, <><b>{d[labelKey]}</b><br />{fmt(d[valueKey])}</>)}
               onMouseLeave={hide} onBlur={hide}>
            <span className="small truncate" title={d[labelKey]}>{d[labelKey]}</span>
            <div style={{ background: 'var(--surface-2)', borderRadius: 4, height: Math.min(24, height) }}>
              <div style={{
                width: `${Math.max(d[valueKey] ? 2 : 0, (d[valueKey] / max) * 100)}%`,
                height: '100%', background: 'var(--series-1)', borderRadius: '0 4px 4px 0',
              }} />
            </div>
            <span className="small num" style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
              {fmt(d[valueKey])}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- columns */
/** Histogram of one measure. Only the tallest column is direct-labeled — a
 *  number on every bar is chaos and goes unread; the axis carries the rest. */
export function ColumnChart({ data, labelKey = 'bin', valueKey = 'count', height = 190 }) {
  const { show, hide, node } = useTooltip()
  const values = data.map((d) => d[valueKey])
  const { max, ticks } = niceScale(Math.max(...values, 1))
  const peak = Math.max(...values)
  const plot = height
  const axisBand = 26
  if (!data.length) return <p className="empty">No data yet.</p>
  return (
    <div>
      {node}
      <div style={{ display: 'flex', gap: 8 }}>
        {/* Axis ticks are a column of numbers, so tabular figures align them. */}
        <div style={{ width: 30, height: plot, position: 'relative', fontVariantNumeric: 'tabular-nums' }}>
          {ticks.map((t) => (
            <span key={t} className="small" style={{
              position: 'absolute', right: 0, top: plot - (t / max) * plot - 7,
              color: AXIS, fontSize: 11,
            }}>{fmt(Math.round(t))}</span>
          ))}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ position: 'relative', height: plot }}>
            {ticks.map((t) => (
              <div key={t} style={{
                position: 'absolute', left: 0, right: 0, bottom: (t / max) * plot,
                borderTop: `1px solid ${t === 0 ? 'var(--baseline)' : GRID}`,
              }} />
            ))}
            <div style={{ position: 'absolute', inset: 0, display: 'flex', gap: 4, alignItems: 'flex-end' }}>
              {data.map((d) => {
                const h = (d[valueKey] / max) * plot
                return (
                  <div key={d[labelKey]} style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', position: 'relative' }}
                       tabIndex={0} role="img" aria-label={`${d[labelKey]}: ${d[valueKey]}`}
                       onMouseEnter={(e) => show(e, <><b>{d[labelKey]}</b><br />{fmt(d[valueKey])}</>)}
                       onFocus={(e) => show(e, <><b>{d[labelKey]}</b><br />{fmt(d[valueKey])}</>)}
                       onMouseLeave={hide} onBlur={hide}>
                    {d[valueKey] === peak && peak > 0 && (
                      <span className="small" style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: 11, marginBottom: 2 }}>
                        {fmt(d[valueKey])}
                      </span>
                    )}
                    <div style={{
                      height: Math.max(d[valueKey] ? 2 : 0, h),
                      /* Capped so a wide card never inflates the mark. */
                      maxWidth: 24, width: '100%', margin: '0 auto',
                      background: 'var(--series-1)',
                      borderRadius: '4px 4px 0 0',
                    }} />
                  </div>
                )
              })}
            </div>
          </div>
          {/* The container includes the axis band, so labels never force a nested scroll. */}
          <div style={{ display: 'flex', gap: 4, height: axisBand, alignItems: 'flex-start', paddingTop: 5 }}>
            {data.map((d, i) => (
              <div key={d[labelKey]} style={{ flex: 1, textAlign: 'center', color: AXIS, fontSize: 10.5 }}>
                {i % 2 === 0 ? d[labelKey] : ''}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- lines */
/** Two series on ONE axis — both are counts, so no second scale is invented.
 *  A legend is always present for two series, and each line is direct-labeled
 *  at its end, so identity never rests on color alone. */
export function LineChart({ data, series, height = 200 }) {
  const { show, hide, node } = useTooltip()
  const [hover, setHover] = useState(null)
  const w = 720
  const padL = 34
  const padR = 54
  const padB = 24
  const plotW = w - padL - padR
  const plotH = height - padB

  const { max, ticks } = niceScale(Math.max(1, ...data.flatMap((d) => series.map((s) => d[s.key]))))
  const x = (i) => (data.length <= 1 ? padL : padL + (i / (data.length - 1)) * plotW)
  const y = (v) => plotH - (v / max) * plotH

  const nearest = useCallback((e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * w
    let best = 0
    let bestD = Infinity
    data.forEach((_, i) => {
      const d = Math.abs(x(i) - px)
      if (d < bestD) { bestD = d; best = i }
    })
    return best
  }, [data])

  if (!data.length) return <p className="empty">No data yet.</p>

  return (
    <div>
      {node}
      {/* Legend is always present for two or more series. */}
      <div className="btn-row" style={{ marginBottom: 8 }}>
        {series.map((s) => (
          <span key={s.key} className="small" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)' }}>
            <span style={{ width: 14, height: 2, background: s.color, borderRadius: 2 }} />
            {s.label}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${w} ${height}`} style={{ width: '100%', height: 'auto', overflow: 'visible' }}
           role="img" aria-label={series.map((s) => s.label).join(' and ') + ' over time'}
           onMouseMove={(e) => {
             const i = nearest(e)
             setHover(i)
             show(e, <><b>{data[i].date}</b>{series.map((s) => (
               <div key={s.key}><span className="k">{s.label}: </span>{fmt(data[i][s.key])}</div>
             ))}</>)
           }}
           onMouseLeave={() => { setHover(null); hide() }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={padL + plotW} y1={y(t)} y2={y(t)}
                  stroke={t === 0 ? 'var(--baseline)' : GRID} strokeWidth="1" />
            <text x={padL - 7} y={y(t) + 4} textAnchor="end" fontSize="11" fill={AXIS}>{fmt(Math.round(t))}</text>
          </g>
        ))}
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={0} y2={plotH} stroke={GRID} strokeWidth="1" />
        )}
        {series.map((s) => {
          const pts = data.map((d, i) => `${x(i)},${y(d[s.key])}`).join(' ')
          const last = data[data.length - 1]
          return (
            <g key={s.key}>
              <polyline points={pts} fill="none" stroke={s.color} strokeWidth="2"
                        strokeLinejoin="round" strokeLinecap="round" />
              {/* End marker: r=4 (8px) with a 2px surface ring so overlapping
                  series stay legible where they cross. */}
              <circle cx={x(data.length - 1)} cy={y(last[s.key])} r="4"
                      fill={s.color} stroke="var(--surface-1)" strokeWidth="2" />
              <text x={x(data.length - 1) + 9} y={y(last[s.key]) + 4} fontSize="11"
                    fill="var(--text-secondary)">{fmt(last[s.key])}</text>
            </g>
          )
        })}
        {data.map((d, i) => (
          i % Math.ceil(data.length / 6) === 0 ? (
            <text key={d.date} x={x(i)} y={height - 6} textAnchor="middle" fontSize="10.5" fill={AXIS}>
              {d.date.slice(5)}
            </text>
          ) : null
        ))}
      </svg>
    </div>
  )
}

/** A meter for a single ratio against a limit — the unfilled track is a lighter
 *  step of the same ramp, so state reads across the whole bar. */
export function Meter({ value, max = 100, tone = 'var(--series-1)' }) {
  const pct = Math.min(100, (value / Math.max(1, max)) * 100)
  return (
    <div style={{ background: 'var(--ord-1)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: tone, borderRadius: '0 4px 4px 0' }} />
    </div>
  )
}

export { useTooltip, fmt }
