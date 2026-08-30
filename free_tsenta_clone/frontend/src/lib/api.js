// Single place that talks to the FastAPI backend. Same origin in production,
// proxied by Vite in dev, so no base URL is needed either way.

async function request(url, options = {}) {
  const res = await fetch(url, options)
  const text = await res.text()
  let body = null
  if (text) {
    try { body = JSON.parse(text) } catch { body = text }
  }
  if (!res.ok) {
    const detail = body && typeof body === 'object' ? body.detail : body
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`)
  }
  return body
}

const json = (method) => (url, payload) =>
  request(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

const post = json('POST')
const patch = json('PATCH')

export const api = {
  health: () => request('/api/health'),
  stats: () => request('/api/stats'),
  analytics: () => request('/api/analytics'),
  activity: (limit = 60) => request(`/api/activity?limit=${limit}`),
  scans: () => request('/api/scans'),

  profile: () => request('/api/profile'),
  resumeText: () => request('/api/profile/resume-text'),
  saveProfile: (formData) => request('/api/profile', { method: 'POST', body: formData }),

  preferences: () => request('/api/preferences'),
  savePreferences: (p) => post('/api/preferences', p),

  jobs: (includeDismissed = false) => request(`/api/jobs?include_dismissed=${includeDismissed}`),
  job: (id) => request(`/api/jobs/${id}`),
  addJob: (j) => post('/api/jobs', j),
  importUrl: (url) =>
    request('/api/jobs/import-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ url }),
    }),
  dismissJob: (id, dismissed = true) => post(`/api/jobs/${id}/dismiss?dismissed=${dismissed}`),
  rescore: () => post('/api/jobs/rescore'),

  applications: () => request('/api/applications'),
  application: (id) => request(`/api/applications/${id}`),
  prepare: (jobId) => post('/api/applications/prepare', { job_id: jobId }),
  updateApplication: (id, body) => patch(`/api/applications/${id}`, body),
  approve: (id) => post('/api/applications/approve', { application_id: id, confirm: true }),
  run: (id, autoSubmit) =>
    post('/api/applications/run', { application_id: id, confirm: true, auto_submit: autoSubmit }),
  logEvent: (id, eventType, note = '') =>
    post('/api/events', { application_id: id, event_type: eventType, note }),

  // Pipeline health — reposts, follow-up cadence and per-channel advance rates.
  reposts: (windowDays = 90) => request(`/api/insights/reposts?window_days=${windowDays}`),
  followups: () => request('/api/insights/followups'),
  channels: () => request('/api/insights/channels'),
  legitimacy: (jobId) => request(`/api/jobs/${jobId}/legitimacy`),
  logFollowup: (id) => post(`/api/applications/${id}/followup`),
  states: () => request('/api/states'),

  // Market-wide sources — job discovery that needs no watchlist.
  sources: () => request('/api/sources'),
  toggleSource: (id) => post(`/api/sources/${id}/toggle`),
  testSource: (id) => post(`/api/sources/${id}/test`),
  freshness: () => request('/api/settings/freshness'),
  setFreshness: (days) =>
    request('/api/settings/freshness', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ fresh_days: String(days) }),
    }),
  scanSources: () => post('/api/agent/scan?sources_only=true'),
  scanWatchlist: () => post('/api/agent/scan?watchlist_only=true'),

  // Inbox — closes the tracking loop by reading employer replies.
  mailbox: () => request('/api/mailbox'),
  mailSync: (dryRun = false) => post(`/api/mailbox/sync?dry_run=${dryRun}`),

  // Which model the agent calls, and a one-shot check that it actually works.
  llm: () => request('/api/llm'),
  testLlm: () => post('/api/llm/test'),

  providers: () => request('/api/providers'),
  detectProvider: (url) =>
    request('/api/providers/detect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ url }),
    }),
  testFilter: (titles, keywords, excludedTitles) =>
    post(`/api/preferences/test-filter?keywords=${encodeURIComponent(keywords || '')}` +
         `&excluded_titles=${encodeURIComponent(excludedTitles || '')}`, titles),

  watchlist: () => request('/api/watchlist'),
  addWatch: (w) => post('/api/watchlist', w),
  toggleWatch: (id) => post(`/api/watchlist/${id}/toggle`),
  deleteWatch: (id) => request(`/api/watchlist/${id}`, { method: 'DELETE' }),
  scan: () => post('/api/agent/scan'),
}
