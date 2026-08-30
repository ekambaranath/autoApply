// Status is a *state*, so it wears the reserved status palette — and every
// badge renders its label beside the dot, so color is never the only channel.
const STATUS_TONE = {
  READY_FOR_REVIEW: 'neutral',
  APPROVED: 'good',
  READY_TO_SUBMIT: 'good',
  SUBMITTED: 'good',
  SECURITY_CHALLENGE: 'warning',
  NEEDS_USER_INPUT: 'warning',
  ERROR: 'critical',
  STARTED: 'neutral',
  NEW: 'neutral',
  REPLIED: 'good',
  INTERVIEW: 'good',
  OFFER: 'good',
  REJECTED: 'serious',
  WITHDRAWN: 'neutral',
  PREPARED: 'neutral',
  EDITED: 'neutral',
  NOTE: 'neutral',
  COMPLETED: 'good',
  RUNNING: 'neutral',
}

export const TONE_VAR = {
  good: 'var(--status-good)',
  warning: 'var(--status-warning)',
  serious: 'var(--status-serious)',
  critical: 'var(--status-critical)',
  neutral: 'var(--text-muted)',
}

export const statusTone = (status) => STATUS_TONE[status] || 'neutral'

export const humanStatus = (s) =>
  String(s || '').replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase())

export function compact(n) {
  const v = Number(n || 0)
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (Math.abs(v) >= 10_000) return `${(v / 1000).toFixed(1)}K`
  return v.toLocaleString()
}

export function timeAgo(iso) {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const secs = Math.round((Date.now() - then) / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export const dateOnly = (iso) => (iso ? new Date(iso).toLocaleDateString() : '—')

export const hostOf = (url) => {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url || '' }
}

/** Line-level diff (LCS) so the tailored resume can be reviewed against the original. */
export function diffLines(before, after) {
  const a = String(before || '').split('\n')
  const b = String(after || '').split('\n')
  const n = a.length
  const m = b.length
  // Guard the O(n*m) table against pathologically large resumes.
  if (n * m > 4_000_000) {
    return [
      ...a.map((text) => ({ type: 'del', text })),
      ...b.map((text) => ({ type: 'add', text })),
    ]
  }
  const lcs = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const out = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ type: 'same', text: a[i] }); i++; j++ }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { out.push({ type: 'del', text: a[i] }); i++ }
    else { out.push({ type: 'add', text: b[j] }); j++ }
  }
  while (i < n) out.push({ type: 'del', text: a[i++] })
  while (j < m) out.push({ type: 'add', text: b[j++] })
  return out
}
