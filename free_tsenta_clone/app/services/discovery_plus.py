"""Watchlist scanning: run each company's ATS provider, fall back to crawling.

Provider adapters live in `providers.py`; this module decides which one to run
for each watchlist entry, applies the user's title filter, and records the run.
"""
import json
import re

import httpx
from bs4 import BeautifulSoup

from . import aggregators as A
from . import providers as P
from .core import db, now, get_prefs, get_setting
from .discovery import save_job
from .title_filter import build_title_filter

UA = 'OpenCareerAgent/4.0 (+local-first)'


def ats_from_url(url):
    """Name the ATS behind a posting URL, for grouping and channel stats."""
    provider, _slug = P.detect(url)
    if provider:
        return provider
    u = (url or '').lower()
    for name in ['workday', 'greenhouse', 'lever', 'ashby', 'rippling', 'icims', 'bamboohr',
                 'workable', 'jazzhr', 'jobvite', 'breezy', 'oracle', 'smartrecruiters',
                 'paylocity', 'ultipro', 'adp', 'dover', 'gem', 'zoho', 'teamtailor',
                 'personio', 'recruitee', 'pinpoint', 'comeet', 'join']:
        if name in u:
            return name
    return 'unknown'


def crawl_page(company, url):
    """Best-effort extraction for a career page with no known ATS behind it."""
    r = httpx.get(url, timeout=30, follow_redirects=True, headers={'User-Agent': UA})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    text = soup.get_text('\n', strip=True)
    title = soup.title.get_text(' ', strip=True) if soup.title else f'{company} careers'
    links = []
    for a in soup.find_all('a', href=True):
        label = a.get_text(' ', strip=True)
        if re.search(r'job|career|position|opening|engineer|developer|scientist|manager',
                     f'{label} {a["href"]}', re.I):
            links.append((label, a['href']))
    return title, text, links


def _title_filter():
    """Build the user's title filter from preferences.

    `keywords` are positive terms and `excluded_titles` are vetoes. Both accept
    the `word:` / `stem:` prefixes and " + " AND-groups.
    """
    prefs = get_prefs() or {}
    return build_title_filter(positive=prefs.get('keywords', ''),
                              negative=prefs.get('excluded_titles', ''))


def _scan_entry(w, keep_title):
    """Scan one watchlist entry. Returns (jobs_saved, jobs_filtered)."""
    company, platform = w['company'], (w['platform'] or '').lower()
    saved = filtered = 0

    if platform in P.PROVIDERS:
        for j in P.fetch(platform, company, slug=w.get('slug') or '', url=w.get('url') or ''):
            if not j['url'] or not j['title']:
                continue
            if not keep_title(j['title']):
                filtered += 1
                continue
            save_job(j['title'], j['company'] or company, j['location'], j['url'],
                     j['description'], platform, platform, j.get('posted_at'))
            saved += 1
        return saved, filtered

    # No known ATS: crawl the page and follow links that look like postings.
    _t, _text, links = crawl_page(company, w['url'])
    for label, href in links[:100]:
        if href.startswith('/'):
            href = w['url'].rstrip('/') + href
        if not href.startswith('http'):
            continue
        if label and not keep_title(label):
            filtered += 1
            continue
        try:
            rr = httpx.get(href, timeout=15, follow_redirects=True, headers={'User-Agent': UA})
            desc = BeautifulSoup(rr.text, 'html.parser').get_text('\n', strip=True)
            if len(desc) > 500:
                save_job(label or 'Open role', company, '', str(rr.url), desc,
                         'career_page', ats_from_url(str(rr.url)))
                saved += 1
        except Exception:
            pass
    return saved, filtered


def active_sources():
    """Enabled aggregator ids, seeded with a sensible default on first run."""
    c = db()
    rows = {r['id']: r['active'] for r in c.execute('SELECT id,active FROM sources')}
    if not rows:
        for sid in A.DEFAULT_ENABLED:
            c.execute('INSERT OR IGNORE INTO sources(id,active) VALUES(?,1)', (sid,))
        c.commit()
        rows = {sid: 1 for sid in A.DEFAULT_ENABLED}
    c.close()
    return [sid for sid, active in rows.items() if active and sid in A.AGGREGATORS]


def scan_sources(trigger='manual', max_age_days=None):
    """Pull fresh postings from every enabled aggregator.

    Unlike the watchlist path this needs no company list: the sources are
    market-wide, so new postings arrive on their own. Results still go through
    the same title filter and the same URL-dedup as everything else.
    """
    import uuid as _uuid
    prefs = get_prefs() or {}
    query = prefs.get('keywords') or prefs.get('roles') or ''
    location = prefs.get('locations') or ''
    if max_age_days is None:
        max_age_days = int(get_setting('fresh_days', '30') or 30)
    keep_title = _title_filter()

    run_id = _uuid.uuid4().hex
    started = now()
    sources = active_sources()
    c = db()
    c.execute('INSERT INTO scan_runs(id,trigger,status,jobs_found,companies,detail,error,'
              'started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?)',
              (run_id, f'sources:{trigger}', 'RUNNING', 0, len(sources), '[]', None, started, None))
    c.commit(); c.close()

    out, total = [], 0
    for sid in sources:
        saved = filtered = stale = 0
        error = None
        try:
            for j in A.fetch(sid, query=query, location=location):
                if not A.is_fresh(j, max_age_days):
                    stale += 1
                    continue
                if not keep_title(j['title']):
                    filtered += 1
                    continue
                save_job(j['title'], j['company'], j['location'], j['url'], j['description'],
                         f'aggregator:{sid}', ats_from_url(j['url']), j.get('posted_at'))
                saved += 1
        except Exception as e:
            error = str(e)
        total += saved
        entry = {'source': sid, 'count': saved}
        if filtered:
            entry['filtered_by_title'] = filtered
        if stale:
            entry['too_old'] = stale
        if error:
            entry['error'] = error
        out.append(entry)
        c = db()
        c.execute('INSERT INTO sources(id,active,last_run,last_count,last_error) VALUES(?,1,?,?,?) '
                  'ON CONFLICT(id) DO UPDATE SET last_run=excluded.last_run,'
                  'last_count=excluded.last_count,last_error=excluded.last_error',
                  (sid, now(), saved, error))
        c.commit(); c.close()

    c = db()
    c.execute('UPDATE scan_runs SET status=?,jobs_found=?,detail=?,finished_at=? WHERE id=?',
              ('COMPLETED', total, json.dumps(out), now(), run_id))
    c.commit(); c.close()
    return out


def scan_all(trigger='manual'):
    """Both discovery paths: market-wide sources first, then the watchlist."""
    return {'sources': scan_sources(trigger), 'watchlist': scan_watchlist(trigger)}


def scan_watchlist(trigger='manual'):
    """Scan every active watchlist entry and record the run for the activity feed."""
    import uuid as _uuid
    run_id = _uuid.uuid4().hex
    started = now()
    c = db()
    c.execute('INSERT INTO scan_runs(id,trigger,status,jobs_found,companies,detail,error,'
              'started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?)',
              (run_id, trigger, 'RUNNING', 0, 0, '[]', None, started, None))
    c.commit()
    rows = [dict(x) for x in c.execute('SELECT * FROM watchlist WHERE active=1')]
    c.close()

    keep_title = _title_filter()
    out, total = [], 0
    for w in rows:
        try:
            saved, filtered = _scan_entry(w, keep_title)
            total += saved
            entry = {'company': w['company'], 'platform': w['platform'], 'count': saved}
            if filtered:
                entry['filtered_by_title'] = filtered
            out.append(entry)
        except Exception as e:
            out.append({'company': w['company'], 'platform': w['platform'], 'error': str(e)})

    c = db()
    c.execute('UPDATE scan_runs SET status=?,jobs_found=?,companies=?,detail=?,finished_at=? WHERE id=?',
              ('COMPLETED', total, len(rows), json.dumps(out), now(), run_id))
    c.commit()
    c.close()
    return out
