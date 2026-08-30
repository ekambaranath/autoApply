import csv, datetime as dt, io, json, os, re, uuid, collections
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document
from .services.core import *
from .services.discovery import save_job, import_url
from .services.discovery_plus import scan_watchlist, ats_from_url
from .services.ats_agent import run_application
from .services import scheduler, providers, insights, states
from .services.title_filter import build_title_filter

app = FastAPI(title='Open Career Agent', version='4.0.0')
ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'frontend' / 'dist'


def extract(name, data):
    if name.lower().endswith('.pdf'):
        return '\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages)
    if name.lower().endswith('.docx'):
        return '\n'.join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    return data.decode('utf-8', 'ignore')


@app.on_event('startup')
def boot(): scheduler.start()


@app.on_event('shutdown')
def shutdown(): scheduler.stop()


@app.get('/api/health')
def health():
    return {'ok': True, 'version': '4.0.0', 'local_first': True, 'scheduler': scheduler.status()}


# ---------------------------------------------------------------- profile
@app.get('/api/profile')
def profile_api():
    p = get_profile() or {}
    p.pop('resume_text', None)
    return p


@app.get('/api/profile/resume-text')
def profile_resume_text():
    p = get_profile() or {}
    return {'resume_text': p.get('resume_text', ''), 'resume_file': p.get('resume_file', '')}


@app.post('/api/profile')
def profile_save(name: str = Form(''), email: str = Form(''), phone: str = Form(''), location: str = Form(''),
                 linkedin: str = Form(''), github: str = Form(''), resume: UploadFile = File(None)):
    """Save profile fields. The resume is optional after the first upload."""
    existing = get_profile() or {}
    text, fn = existing.get('resume_text', ''), existing.get('resume_file', '')
    if resume is not None and resume.filename:
        raw = resume.file.read()
        text = extract(resume.filename, raw)
        fn = uuid.uuid4().hex + '_' + Path(resume.filename).name
        (STORAGE / fn).write_bytes(raw)
    if not text:
        raise HTTPException(400, 'A resume is required the first time you save your profile')
    t = now()
    c = db()
    c.execute('DELETE FROM profile')
    c.execute('INSERT INTO profile(name,email,phone,location,linkedin,github,resume_text,resume_file,created_at,updated_at)'
              ' VALUES(?,?,?,?,?,?,?,?,?,?)',
              (name, email, phone, location, linkedin, github, text, fn, existing.get('created_at') or t, t))
    c.commit(); c.close()
    return {'ok': True, 'characters': len(text), 'resume_file': fn}


# ------------------------------------------------------------ preferences
class PrefIn(BaseModel):
    roles: str = ''
    locations: str = ''
    remote: str = 'Any'
    min_salary: int = 0
    max_salary: int = 0
    work_auth: str = ''
    sponsorship: str = 'Any'
    excluded_companies: str = ''
    keywords: str = ''
    # Title vetoes. Supports `word:` / `stem:` prefixes and " + " AND-groups.
    excluded_titles: str = ''
    auto_apply: bool = False
    review_required: bool = True


@app.get('/api/preferences')
def prefs_get(): return get_prefs()


@app.post('/api/preferences')
def prefs_save(x: PrefIn):
    c = db()
    c.execute('DELETE FROM preferences')
    c.execute('INSERT INTO preferences(roles,locations,remote,min_salary,max_salary,work_auth,sponsorship,'
              'excluded_companies,keywords,excluded_titles,auto_apply,review_required,updated_at)'
              ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (x.roles, x.locations, x.remote, x.min_salary, x.max_salary, x.work_auth, x.sponsorship,
               x.excluded_companies, x.keywords, x.excluded_titles,
               int(x.auto_apply), int(x.review_required), now()))
    c.commit(); c.close()
    return {'ok': True}


@app.post('/api/preferences/test-filter')
def prefs_test_filter(titles: list[str], keywords: str = '', excluded_titles: str = ''):
    """Preview which titles a filter keeps, so it can be tuned before a scan.

    A filter that silently drops everything is the failure mode worth catching
    here: the scan summary only reports one "filtered by title" count, which
    cannot tell a well-tuned filter from a leaking one.
    """
    keep = build_title_filter(positive=keywords, negative=excluded_titles)
    return [{'title': t, 'kept': keep(t)} for t in titles]


# ------------------------------------------------------------------- jobs
class JobIn(BaseModel):
    title: str
    company: str = ''
    location: str = ''
    url: str
    description: str
    source: str = 'manual'
    ats: str = 'unknown'


@app.post('/api/jobs')
def job_add(x: JobIn):
    return {'id': save_job(x.title, x.company, x.location, x.url, x.description, x.source, x.ats), 'ok': True}


class PageJob(BaseModel):
    url: str
    title: str = ''
    text: str = ''


@app.post('/api/jobs/from-page')
def job_from_page(x: PageJob):
    text = x.text or ''
    if len(text) < 300:
        try:
            return {'id': import_url(x.url), 'ok': True}
        except Exception:
            pass
    return {'id': save_job(x.title or 'Imported role', '', '', x.url, text, 'chrome_extension', 'unknown'), 'ok': True}


@app.post('/api/jobs/import-url')
def job_import(url: str = Form(...)):
    try:
        return {'id': import_url(url), 'ok': True}
    except Exception as e:
        raise HTTPException(400, f'Could not import that URL: {e}')


@app.get('/api/jobs')
def jobs(include_dismissed: bool = False):
    c = db()
    sql = 'SELECT * FROM jobs' + ('' if include_dismissed else ' WHERE COALESCE(dismissed,0)=0')
    r = [dict(x) for x in c.execute(sql + ' ORDER BY match_score DESC,created_at DESC')]
    c.close()
    for x in r:
        x['match_reasons'] = _loads(x.get('match_reasons'), [])
    return r


@app.get('/api/jobs/{jid}')
def job_detail(jid: str):
    c = db()
    j = c.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
    if not j:
        c.close(); raise HTTPException(404, 'Job not found')
    j = dict(j)
    j['match_reasons'] = _loads(j.get('match_reasons'), [])
    j['applications'] = [dict(x) for x in c.execute(
        'SELECT id,status,created_at,updated_at FROM applications WHERE job_id=? ORDER BY created_at DESC', (jid,))]
    c.close()
    return j


@app.post('/api/jobs/{jid}/dismiss')
def job_dismiss(jid: str, dismissed: bool = True):
    c = db()
    c.execute('UPDATE jobs SET dismissed=? WHERE id=?', (int(dismissed), jid))
    changed = c.total_changes
    c.commit(); c.close()
    if not changed:
        raise HTTPException(404, 'Job not found')
    return {'ok': True, 'dismissed': dismissed}


@app.post('/api/jobs/rescore')
def jobs_rescore():
    """Re-score every job against the current resume and preferences."""
    p = get_profile() or {}
    prefs = get_prefs()
    resume = p.get('resume_text', '')
    c = db()
    rows = [dict(x) for x in c.execute('SELECT id,description FROM jobs')]
    for j in rows:
        score, reasons = score_job(j['description'], resume, prefs)
        c.execute('UPDATE jobs SET match_score=?,match_reasons=? WHERE id=?',
                  (score, json.dumps(reasons), j['id']))
    c.commit(); c.close()
    return {'ok': True, 'rescored': len(rows)}


# -------------------------------------------------------------- watchlist
class WatchIn(BaseModel):
    company: str
    platform: str = 'auto'
    slug: str = ''
    url: str = ''


@app.get('/api/providers')
def providers_list():
    """The ATS boards with a real adapter, and what each needs as a slug."""
    return [{'id': pid, 'slug_help': providers.SLUG_HELP.get(pid, '')}
            for pid in sorted(providers.PROVIDERS)]


@app.post('/api/providers/detect')
def providers_detect(url: str = Form(...)):
    provider, slug = providers.detect(url)
    return {'provider': provider, 'slug': slug,
            'slug_help': providers.SLUG_HELP.get(provider, '') if provider else ''}


@app.post('/api/watchlist')
def watch_add(x: WatchIn):
    """Add a company to the watchlist.

    Pasting a careers URL is enough: the provider and its board slug are
    detected from the URL, and anything unrecognised falls back to crawling.
    """
    platform, slug = x.platform, x.slug
    if platform in ('', 'auto'):
        detected, detected_slug = providers.detect(x.url)
        platform = detected or 'career_page'
        slug = slug or detected_slug
    if platform in providers.PROVIDERS and not slug:
        _p, detected_slug = providers.detect(x.url)
        slug = detected_slug
        if not slug:
            raise HTTPException(
                400, f'{platform} entries need a board slug — {providers.SLUG_HELP.get(platform, "")}')
    if platform not in providers.PROVIDERS and not x.url:
        raise HTTPException(400, 'Career-page entries need a URL')
    c = db()
    c.execute('INSERT INTO watchlist(company,platform,slug,url,created_at) VALUES(?,?,?,?,?)',
              (x.company, platform, slug, x.url, now()))
    c.commit(); c.close()
    return {'ok': True, 'platform': platform, 'slug': slug}


@app.get('/api/watchlist')
def watch():
    c = db()
    r = [dict(x) for x in c.execute('SELECT * FROM watchlist ORDER BY company')]
    c.close()
    return r


@app.post('/api/watchlist/{wid}/toggle')
def watch_toggle(wid: int):
    c = db()
    row = c.execute('SELECT active FROM watchlist WHERE id=?', (wid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(404, 'Watchlist entry not found')
    new = 0 if row['active'] else 1
    c.execute('UPDATE watchlist SET active=? WHERE id=?', (new, wid))
    c.commit(); c.close()
    return {'ok': True, 'active': bool(new)}


@app.delete('/api/watchlist/{wid}')
def watch_delete(wid: int):
    c = db()
    c.execute('DELETE FROM watchlist WHERE id=?', (wid,))
    changed = c.total_changes
    c.commit(); c.close()
    if not changed:
        raise HTTPException(404, 'Watchlist entry not found')
    return {'ok': True}


# -------------------------------------------------------------- discovery
@app.post('/api/discovery/sync')
def sync(): return scan_watchlist(trigger='manual')


@app.post('/api/agent/scan')
def agent_scan(): return {'results': scan_watchlist(trigger='manual')}


@app.get('/api/scans')
def scans(limit: int = 25):
    c = db()
    r = [dict(x) for x in c.execute('SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT ?', (limit,))]
    c.close()
    for x in r:
        x['detail'] = _loads(x.get('detail'), [])
    return r


# ----------------------------------------------------------- applications
class Prep(BaseModel):
    job_id: str


PREP_PROMPT = (
    'You are a strict career-agent editor. Use ONLY facts in RESUME. Never invent metrics, employers, titles, '
    'dates, skills, degrees, authorization or experience. Return valid JSON with tailored_resume, cover_letter, '
    'answers, change_log. Tailored resume must preserve factual claims and only reorder/rephrase. answers is a '
    'JSON object. Unknown personal facts must be NEEDS_USER_INPUT. change_log is an array of concise changes.\n'
    'RESUME:\n{resume}\nJOB:\n{job}'
)


@app.post('/api/applications/prepare')
def prepare(x: Prep):
    p = get_profile()
    c = db()
    j = c.execute('SELECT * FROM jobs WHERE id=?', (x.job_id,)).fetchone()
    c.close()
    if not p or not j:
        raise HTTPException(404, 'Profile or job missing')
    raw = llm(PREP_PROMPT.format(resume=p['resume_text'][:50000], job=j['description'][:50000]))
    data = {}
    if raw:
        m = re.search(r'\{.*\}', raw, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = {}
    if not data:
        data = {
            'tailored_resume': p['resume_text'],
            'cover_letter': (f'Dear Hiring Team,\n\nI am applying for the {j["title"]} role at '
                             f'{j["company"] or "your company"}. My background aligns with the requirements described '
                             f'in the posting, and I would welcome the opportunity to discuss the role.\n\nRegards,\n'
                             f'{p["name"]}'),
            'answers': {'work_authorization': 'NEEDS_USER_INPUT', 'sponsorship': 'NEEDS_USER_INPUT'},
            'change_log': ['Fallback: original resume preserved (no LLM response).'],
        }
    aid = uuid.uuid4().hex
    t = now()
    c = db()
    c.execute('INSERT INTO applications(id,job_id,status,tailored_resume,cover_letter,answers,receipt,created_at,updated_at)'
              ' VALUES(?,?,?,?,?,?,?,?,?)',
              (aid, x.job_id, 'READY_FOR_REVIEW', data.get('tailored_resume', ''), data.get('cover_letter', ''),
               json.dumps(data.get('answers', {})),
               json.dumps({'prepared_at': t, 'change_log': data.get('change_log', [])}), t, t))
    c.execute('INSERT INTO resume_versions VALUES(?,?,?,?,?)',
              (uuid.uuid4().hex, x.job_id, data.get('tailored_resume', ''),
               json.dumps({'generated': True, 'change_log': data.get('change_log', [])}), t))
    c.commit(); c.close()
    audit(aid, 'PREPARED', {'job_id': x.job_id, 'change_log': data.get('change_log', [])})
    return {'id': aid, 'status': 'READY_FOR_REVIEW', **data}


@app.get('/api/applications')
def apps(status: str = ''):
    c = db()
    sql = ('SELECT a.*,j.title,j.company,j.location,j.url,j.ats,j.match_score FROM applications a '
           'JOIN jobs j ON j.id=a.job_id')
    params = ()
    if status:
        sql += ' WHERE a.status=?'; params = (status,)
    r = [dict(x) for x in c.execute(sql + ' ORDER BY a.created_at DESC', params)]
    c.close()
    for x in r:
        x['answers'] = _loads(x.get('answers'), {})
        x['receipt'] = _loads(x.get('receipt'), {})
        x['needs_input'] = [k for k, v in x['answers'].items() if v == 'NEEDS_USER_INPUT']
        # The list view does not need full documents; the detail endpoint carries them.
        x.pop('tailored_resume', None)
        x.pop('cover_letter', None)
    return r


@app.get('/api/applications/{aid}')
def app_detail(aid: str):
    c = db()
    a = c.execute('SELECT a.*,j.title,j.company,j.location,j.url,j.ats,j.match_score,j.description,'
                  'j.match_reasons FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?', (aid,)).fetchone()
    if not a:
        c.close(); raise HTTPException(404, 'Application not found')
    a = dict(a)
    a['answers'] = _loads(a.get('answers'), {})
    a['receipt'] = _loads(a.get('receipt'), {})
    a['match_reasons'] = _loads(a.get('match_reasons'), [])
    a['needs_input'] = [k for k, v in a['answers'].items() if v == 'NEEDS_USER_INPUT']
    a['events'] = [dict(x) for x in c.execute(
        'SELECT * FROM events WHERE application_id=? ORDER BY created_at', (aid,))]
    for e in a['events']:
        e['payload'] = _loads(e.get('payload'), {})
    a['versions'] = [dict(x) for x in c.execute(
        'SELECT id,content,changes,created_at FROM resume_versions WHERE job_id=? ORDER BY created_at DESC',
        (a['job_id'],))]
    c.close()
    for v in a['versions']:
        v['changes'] = _loads(v.get('changes'), {})
    p = get_profile() or {}
    a['original_resume'] = p.get('resume_text', '')
    a['has_screenshot'] = bool(a.get('screenshot_file') and (STORAGE / a['screenshot_file']).exists())
    return a


class AppPatch(BaseModel):
    tailored_resume: str | None = None
    cover_letter: str | None = None
    answers: dict | None = None
    notes: str | None = None


@app.patch('/api/applications/{aid}')
def app_patch(aid: str, x: AppPatch):
    """Edit a prepared application before approval — this is how NEEDS_USER_INPUT gets resolved."""
    c = db()
    row = c.execute('SELECT * FROM applications WHERE id=?', (aid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(404, 'Application not found')
    if row['status'] in ('SUBMITTED',):
        c.close(); raise HTTPException(409, 'A submitted application cannot be edited')
    sets, params = [], []
    for col, val in (('tailored_resume', x.tailored_resume), ('cover_letter', x.cover_letter), ('notes', x.notes)):
        if val is not None:
            sets.append(f'{col}=?'); params.append(val)
    if x.answers is not None:
        sets.append('answers=?'); params.append(json.dumps(x.answers))
    if not sets:
        c.close(); return {'ok': True, 'unchanged': True}
    sets.append('updated_at=?'); params.append(now()); params.append(aid)
    c.execute(f'UPDATE applications SET {",".join(sets)} WHERE id=?', params)
    c.commit(); c.close()
    if x.tailored_resume is not None and x.tailored_resume != row['tailored_resume']:
        t = now()
        c = db()
        c.execute('INSERT INTO resume_versions VALUES(?,?,?,?,?)',
                  (uuid.uuid4().hex, row['job_id'], x.tailored_resume,
                   json.dumps({'generated': False, 'change_log': ['Edited by user']}), t))
        c.commit(); c.close()
    audit(aid, 'EDITED', {'fields': [s.split('=')[0] for s in sets if not s.startswith('updated_at')]})
    return {'ok': True}


class ApplyIn(BaseModel):
    application_id: str
    confirm: bool = False
    auto_submit: bool = False


@app.post('/api/applications/approve')
def approve(x: ApplyIn):
    if not x.confirm:
        raise HTTPException(400, 'Explicit confirmation required')
    c = db()
    r = c.execute('SELECT * FROM applications WHERE id=?', (x.application_id,)).fetchone()
    if not r:
        c.close(); raise HTTPException(404, 'Application not found')
    answers = _loads(r['answers'], {})
    pending = [k for k, v in answers.items() if v == 'NEEDS_USER_INPUT']
    if pending:
        c.close(); raise HTTPException(409, f'Answer these fields before approving: {", ".join(pending)}')
    t = now()
    receipt = {'approved_at': t, 'next_step': 'run /api/applications/run',
               'security_note': 'CAPTCHA/MFA challenges require user action.'}
    c.execute('UPDATE applications SET status=?,receipt=?,updated_at=? WHERE id=?',
              ('APPROVED', json.dumps(receipt), t, x.application_id))
    c.commit(); c.close()
    audit(x.application_id, 'APPROVED', receipt)
    return receipt


@app.post('/api/applications/run')
async def run_apply(x: ApplyIn):
    if not x.confirm:
        raise HTTPException(400, 'Explicit confirmation required')
    c = db()
    a = c.execute('SELECT a.*,j.url AS job_url FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?',
                  (x.application_id,)).fetchone()
    c.close()
    if not a:
        raise HTTPException(404, 'Application not found')
    p = get_profile() or {}
    answers = _loads(a['answers'], {})
    pending = [k for k, v in answers.items() if v == 'NEEDS_USER_INPUT']
    if pending:
        raise HTTPException(409, f'Answer these fields first: {", ".join(pending)}')
    resume = str(STORAGE / p.get('resume_file', ''))
    result = await run_application(a['job_url'], p, answers, resume, a['cover_letter'],
                                   auto_submit=x.auto_submit, headless=True)
    t = now()
    safe = {k: v for k, v in result.items() if k != 'screenshot_bytes'}
    shot = result.get('screenshot_bytes')
    shot_name = None
    if shot:
        shot_name = f'{x.application_id}_{uuid.uuid4().hex[:8]}.png'
        (STORAGE / shot_name).write_bytes(shot)
    status = result.get('status', 'READY_TO_SUBMIT')
    c = db()
    if shot_name:
        c.execute('UPDATE applications SET status=?,receipt=?,screenshot_file=?,updated_at=? WHERE id=?',
                  (status, json.dumps(safe), shot_name, t, x.application_id))
    else:
        c.execute('UPDATE applications SET status=?,receipt=?,updated_at=? WHERE id=?',
                  (status, json.dumps(safe), t, x.application_id))
    c.commit(); c.close()
    audit(x.application_id, status, safe)
    return {'status': status, 'submitted': result.get('submitted', False), 'receipt': safe,
            'has_screenshot': bool(shot_name)}


@app.get('/api/applications/{aid}/events')
def events(aid: str):
    c = db()
    r = [dict(x) for x in c.execute('SELECT * FROM events WHERE application_id=? ORDER BY created_at', (aid,))]
    c.close()
    for e in r:
        e['payload'] = _loads(e.get('payload'), {})
    return r


@app.get('/api/applications/{aid}/screenshot')
def screenshot(aid: str):
    c = db()
    r = c.execute('SELECT screenshot_file FROM applications WHERE id=?', (aid,)).fetchone()
    c.close()
    if not r or not r['screenshot_file']:
        raise HTTPException(404, 'No screenshot for this application')
    path = STORAGE / r['screenshot_file']
    if not path.exists():
        raise HTTPException(404, 'Screenshot file is missing from storage')
    return Response(path.read_bytes(), media_type='image/png')


class EventIn(BaseModel):
    application_id: str
    event_type: str
    note: str = ''


@app.post('/api/events')
def event_add(x: EventIn):
    """Log an outcome you heard about outside the agent — a reply, a rejection, an interview."""
    allowed = {'REPLIED', 'INTERVIEW', 'REJECTED', 'OFFER', 'NOTE', 'WITHDRAWN'}
    if x.event_type not in allowed:
        raise HTTPException(400, f'event_type must be one of {", ".join(sorted(allowed))}')
    c = db()
    if not c.execute('SELECT 1 FROM applications WHERE id=?', (x.application_id,)).fetchone():
        c.close(); raise HTTPException(404, 'Application not found')
    c.close()
    audit(x.application_id, x.event_type, {'note': x.note})
    return {'ok': True}


# --------------------------------------------------------------- activity
@app.get('/api/activity')
def activity(limit: int = 50):
    """Merged feed of agent events and scan runs, newest first."""
    c = db()
    evs = [dict(x) for x in c.execute(
        'SELECT e.id,e.application_id,e.event_type,e.payload,e.created_at,j.title,j.company '
        'FROM events e LEFT JOIN applications a ON a.id=e.application_id '
        'LEFT JOIN jobs j ON j.id=a.job_id ORDER BY e.created_at DESC LIMIT ?', (limit,))]
    runs = [dict(x) for x in c.execute('SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT ?', (limit,))]
    c.close()
    feed = [{'kind': 'event', 'id': e['id'], 'at': e['created_at'], 'type': e['event_type'],
             'application_id': e['application_id'], 'title': e['title'], 'company': e['company'],
             'payload': _loads(e.get('payload'), {})} for e in evs]
    feed += [{'kind': 'scan', 'id': r['id'], 'at': r['started_at'], 'type': r['status'],
              'trigger': r['trigger'], 'jobs_found': r['jobs_found'], 'companies': r['companies'],
              'detail': _loads(r.get('detail'), [])} for r in runs]
    feed.sort(key=lambda x: x['at'] or '', reverse=True)
    return feed[:limit]


# -------------------------------------------------------- stats/analytics
@app.get('/api/stats')
def stats():
    c = db()
    one = lambda q, *p: c.execute(q, p).fetchone()['n']
    vals = {
        'jobs': one('SELECT count(*) n FROM jobs WHERE COALESCE(dismissed,0)=0'),
        'matches': one('SELECT count(*) n FROM jobs WHERE match_score>=70 AND COALESCE(dismissed,0)=0'),
        'applications': one('SELECT count(*) n FROM applications'),
        'approved': one("SELECT count(*) n FROM applications WHERE status='APPROVED'"),
        'submitted': one("SELECT count(*) n FROM applications WHERE status='SUBMITTED'"),
        'responses': one("SELECT count(*) n FROM events WHERE event_type IN ('REPLIED','INTERVIEW','OFFER')"),
        'needs_attention': one("SELECT count(*) n FROM applications WHERE status IN ('SECURITY_CHALLENGE','ERROR')"),
    }
    c.close()
    return vals


@app.get('/api/analytics')
def analytics():
    """Everything the dashboard charts need, in one round trip."""
    c = db()
    all_jobs = [dict(x) for x in c.execute(
        'SELECT company,ats,source,match_score,created_at,COALESCE(dismissed,0) AS dismissed FROM jobs')]
    # The funnel counts every job ever discovered — dismissing one is triage, not un-discovery.
    # The distribution/breakdown charts describe the live pipeline, so they exclude dismissed jobs.
    jobs_rows = [j for j in all_jobs if not j['dismissed']]
    app_rows = [dict(x) for x in c.execute('SELECT status,created_at FROM applications')]
    responses = c.execute(
        "SELECT count(*) n FROM events WHERE event_type IN ('REPLIED','INTERVIEW','OFFER')").fetchone()['n']
    prepared = len(app_rows)
    approved = c.execute(
        "SELECT count(*) n FROM applications WHERE status IN ('APPROVED','READY_TO_SUBMIT','SUBMITTED')"
    ).fetchone()['n']
    submitted = c.execute("SELECT count(*) n FROM applications WHERE status='SUBMITTED'").fetchone()['n']
    c.close()

    # Match-score histogram in fixed 10-point bins so the x-axis is stable as data arrives.
    bins = collections.OrderedDict((f'{lo}-{lo + 9}', 0) for lo in range(0, 100, 10))
    for j in jobs_rows:
        lo = min(90, max(0, int(j['match_score'] or 0) // 10 * 10))
        bins[f'{lo}-{lo + 9}'] += 1

    def top(key, n=8):
        counts = collections.Counter((j.get(key) or 'unknown') for j in jobs_rows)
        return [{'label': k, 'count': v} for k, v in counts.most_common(n)]

    # Jobs discovered per day, last 30 days present in the data.
    per_day = collections.Counter((j['created_at'] or '')[:10] for j in jobs_rows if j['created_at'])
    apps_per_day = collections.Counter((a['created_at'] or '')[:10] for a in app_rows if a['created_at'])
    days = sorted(set(per_day) | set(apps_per_day))[-30:]

    return {
        'funnel': [
            {'stage': 'Discovered', 'count': len(all_jobs)},
            {'stage': 'Strong match', 'count': sum(1 for j in all_jobs if (j['match_score'] or 0) >= 70)},
            {'stage': 'Prepared', 'count': prepared},
            {'stage': 'Approved', 'count': approved},
            {'stage': 'Submitted', 'count': submitted},
        ],
        'responses': responses,
        'score_bins': [{'bin': k, 'count': v} for k, v in bins.items()],
        'by_company': top('company'),
        'by_ats': top('ats'),
        'by_source': top('source'),
        'by_status': [{'label': k, 'count': v} for k, v in
                      collections.Counter(a['status'] for a in app_rows).most_common()],
        'timeline': [{'date': d, 'jobs': per_day.get(d, 0), 'applications': apps_per_day.get(d, 0)} for d in days],
    }


@app.get('/api/insights/reposts')
def insights_reposts(window_days: int = 90):
    """Roles re-listed at a fresh URL — often a ghost job or a hard-to-fill req."""
    c = db()
    rows = [dict(x) for x in c.execute(
        'SELECT id,company,title,url,posted_at,created_at FROM jobs')]
    c.close()
    return insights.detect_reposts(rows, window_days=window_days)


@app.get('/api/insights/followups')
def insights_followups():
    """Live applications due (or overdue) a nudge, by the configured cadence."""
    c = db()
    rows = [dict(x) for x in c.execute(
        'SELECT a.id,a.status,a.created_at,a.updated_at,a.followups_sent,a.followed_up_at,'
        'j.title,j.company FROM applications a JOIN jobs j ON j.id=a.job_id')]
    c.close()
    return insights.followups(rows)


@app.post('/api/applications/{aid}/followup')
def log_followup(aid: str):
    """Record that a follow-up went out, which restarts that application's clock."""
    c = db()
    row = c.execute('SELECT followups_sent FROM applications WHERE id=?', (aid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(404, 'Application not found')
    sent = (row['followups_sent'] or 0) + 1
    t = now()
    c.execute('UPDATE applications SET followups_sent=?,followed_up_at=?,updated_at=? WHERE id=?',
              (sent, t, t, aid))
    c.commit(); c.close()
    audit(aid, 'NOTE', {'note': f'Follow-up #{sent} sent'})
    return {'ok': True, 'followups_sent': sent}


@app.get('/api/insights/channels')
def insights_channels():
    """Advance rate per ATS: of what was sent, how much drew a reply."""
    c = db()
    rows = [dict(x) for x in c.execute(
        'SELECT a.status,j.ats FROM applications a JOIN jobs j ON j.id=a.job_id')]
    c.close()
    return {'channels': insights.channel_rates(rows),
            'stages': insights.rejection_patterns(rows)}


@app.get('/api/jobs/{jid}/legitimacy')
def job_legitimacy(jid: str):
    """Posting-quality signals, kept deliberately separate from the match score."""
    c = db()
    j = c.execute('SELECT id,company,title,url,description,posted_at,created_at FROM jobs WHERE id=?',
                  (jid,)).fetchone()
    if not j:
        c.close(); raise HTTPException(404, 'Job not found')
    j = dict(j)
    others = [dict(x) for x in c.execute(
        'SELECT id,company,title,url,posted_at,created_at FROM jobs WHERE company=?', (j['company'],))]
    c.close()
    reposts = sum(cl['repost_count'] for cl in insights.detect_reposts(others)
                  if any(a['job_id'] == jid for a in cl['appearances']))
    seen = j.get('created_at')
    age = None
    if seen:
        try:
            age = (dt.datetime.now(dt.timezone.utc) -
                   dt.datetime.fromisoformat(str(seen).replace('Z', '+00:00'))).days
        except Exception:
            age = None
    return insights.legitimacy_signals(j, repost_count=reposts, age_days=age)


@app.get('/api/states')
def states_list():
    """The canonical status roster the UI renders and the API accepts."""
    return [{'id': sid, 'label': lbl, 'terminal': term}
            for sid, lbl, _aliases, term in states.STATES]


@app.get('/api/export.csv')
def export():
    c = db()
    rows = c.execute('SELECT j.company,j.title,j.location,j.url,j.ats,j.match_score,a.status,a.created_at,'
                     'a.updated_at FROM applications a JOIN jobs j ON j.id=a.job_id '
                     'ORDER BY a.created_at DESC').fetchall()
    c.close()
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(['company', 'title', 'location', 'url', 'ats', 'match_score', 'status', 'created_at', 'updated_at'])
    w.writerows(rows)
    return StreamingResponse(iter([s.getvalue()]), media_type='text/csv',
                             headers={'Content-Disposition': 'attachment; filename=career_agent.csv'})


def _loads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except Exception:
        return default


# ------------------------------------------------------- static frontend
# The built React app is served from the same origin as the API. The legacy
# static/index.html is the fallback when the frontend has not been built yet.
if (DIST / 'index.html').exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')

    @app.get('/')
    def spa_root(): return FileResponse(DIST / 'index.html')

    @app.get('/{path:path}')
    def spa_fallback(path: str):
        # An unmatched /api/... path is a genuine 404, not a client-side route.
        if path.startswith('api/'):
            raise HTTPException(404, 'Not found')
        candidate = (DIST / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(DIST / 'index.html')
else:
    @app.get('/')
    def home(): return FileResponse(ROOT / 'static' / 'index.html')
