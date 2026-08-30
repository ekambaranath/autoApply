"""ATS providers: one adapter per job board, plus detection from a careers URL.

The adapter set and the detect-from-URL idea are adapted from career-ops
(MIT, (c) 2026 Santiago Fernandez de Valderrama), whose `providers/` directory
documents each board's public endpoint and response shape.
https://github.com/santifer/career-ops

Every adapter returns a list of plain dicts:
    {title, url, company, location, description, posted_at}
so the caller never needs to know which board a job came from.
"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

UA = 'OpenCareerAgent/4.0 (+local-first)'
TIMEOUT = 30
# Ashby's public posting API has a ~10s server-side latency floor, so the
# default timeout sits right on it and requests race the timeout.
SLOW_TIMEOUT = 45

# Board slugs are alphanumerics plus - and _ . Anything else is rejected rather
# than interpolated, so a crafted careers URL cannot escape the API path.
SLUG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class ProviderError(RuntimeError):
    pass


def _slug(value):
    s = (value or '').strip().strip('/')
    if not SLUG_RE.match(s):
        raise ProviderError(f'Invalid board slug: {value!r}')
    return s


def _get(url, timeout=TIMEOUT, headers=None):
    h = {'User-Agent': UA, 'Accept': 'application/json,text/xml,*/*'}
    h.update(headers or {})
    r = httpx.get(url, timeout=timeout, follow_redirects=True, headers=h)
    r.raise_for_status()
    return r


def _text(html):
    """Flatten an HTML description to readable plain text."""
    if not html:
        return ''
    if '<' not in html:
        return html
    return BeautifulSoup(html, 'html.parser').get_text('\n', strip=True)


def _join(*parts):
    return ', '.join(p for p in (str(x or '').strip() for x in parts) if p)


def _job(title, url, company, location='', description='', posted_at=None):
    return {'title': (title or '').strip(), 'url': (url or '').strip(), 'company': company,
            'location': location or '', 'description': description or '', 'posted_at': posted_at}


# --------------------------------------------------------------- adapters
def greenhouse(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=true').json()
    return [_job(j.get('title'), j.get('absolute_url'), company,
                 (j.get('location') or {}).get('name', ''),
                 _text(j.get('content', '')), j.get('updated_at'))
            for j in data.get('jobs', [])]


def lever(company, slug='', url=''):
    s = _slug(slug)
    out = []
    for j in _get(f'https://api.lever.co/v0/postings/{s}?mode=json').json():
        desc = (j.get('descriptionPlain') or '') + '\n' + '\n'.join(
            x.get('content', '') for x in (j.get('lists') or []))
        out.append(_job(j.get('text'), j.get('hostedUrl'), company,
                        (j.get('categories') or {}).get('location', ''),
                        _text(desc), j.get('createdAt')))
    return out


def ashby(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true',
                timeout=SLOW_TIMEOUT).json()
    out = []
    for j in data.get('jobs', []):
        loc = j.get('location') or _join((j.get('address') or {}).get('postalAddress', {}).get('addressLocality'))
        if j.get('isRemote'):
            loc = _join(loc, 'Remote')
        out.append(_job(j.get('title'), j.get('jobUrl'), company, loc,
                        j.get('descriptionPlain') or _text(j.get('descriptionHtml', '')),
                        j.get('publishedAt')))
    return out


def smartrecruiters(company, slug='', url='', fetch_details=True, detail_limit=60):
    """SmartRecruiters paginates, and its list payload carries no description body."""
    s = _slug(slug)
    base = f'https://api.smartrecruiters.com/v1/companies/{s}/postings'
    out, offset = [], 0
    while True:
        data = _get(f'{base}?limit=100&offset={offset}').json()
        page = data.get('content') or []
        for j in page:
            loc = j.get('location') or {}
            where = _join(loc.get('city'), loc.get('region'), loc.get('country'))
            if loc.get('remote'):
                where = _join(where, 'Remote')
            out.append({'_id': j.get('id'),
                        **_job(j.get('name'), f'https://jobs.smartrecruiters.com/{s}/{j.get("id")}',
                               company, where, '', j.get('releasedDate'))})
        offset += len(page)
        if not page or offset >= (data.get('totalFound') or 0) or offset >= 400:
            break
    if fetch_details:
        for j in out[:detail_limit]:
            try:
                detail = _get(f'{base}/{j["_id"]}').json()
                sections = ((detail.get('jobAd') or {}).get('sections') or {})
                j['description'] = _text('\n'.join(
                    (sections.get(k) or {}).get('text', '') for k in
                    ('companyDescription', 'jobDescription', 'qualifications', 'additionalInformation')))
            except Exception:
                pass
    for j in out:
        j.pop('_id', None)
    return out


def workable(company, slug='', url=''):
    """The widget API returns the account's full posting list in one request."""
    s = _slug(slug)
    data = _get(f'https://apply.workable.com/api/v1/widget/accounts/{s}?details=true').json()
    out = []
    for j in data.get('jobs', []):
        where = _join(j.get('city'), j.get('state'), j.get('country'))
        if j.get('telecommuting'):
            where = _join(where, 'Remote')
        link = j.get('shortlink') or j.get('url') or f'https://apply.workable.com/{s}/j/{j.get("shortcode")}'
        out.append(_job(j.get('title'), link, company or data.get('name') or '', where,
                        _text(j.get('description', '')), j.get('published_on')))
    return out


def recruitee(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://{s}.recruitee.com/api/offers/').json()
    out = []
    for j in data.get('offers', []):
        out.append(_job(j.get('title'), j.get('careers_url') or j.get('url'), company,
                        j.get('location') or _join(j.get('city'), j.get('country')),
                        _text(j.get('description', '')), j.get('published_at')))
    return out


def personio(company, slug='', url=''):
    """Personio publishes an XML feed per tenant."""
    s = _slug(slug)
    root = ET.fromstring(_get(f'https://{s}.jobs.personio.de/xml').content)
    out = []
    for pos in root.iter('position'):
        get = lambda tag: (pos.findtext(tag) or '').strip()
        body = '\n'.join(
            f'{(jd.findtext("name") or "").strip()}\n{_text(jd.findtext("value") or "")}'
            for jd in pos.iter('jobDescription'))
        out.append(_job(get('name'), get('url'), company or get('company'),
                        _join(get('office'), get('department')),
                        body or _text(get('description')), get('createdAt') or None))
    return out


def teamtailor(company, slug='', url=''):
    """Teamtailor exposes an RSS feed; entries carry title, link and summary."""
    import feedparser
    s = _slug(slug)
    feed = feedparser.parse(_get(f'https://{s}.teamtailor.com/jobs.rss').text)
    return [_job(e.get('title'), e.get('link'), company,
                 e.get('location', ''), _text(e.get('summary', '')), e.get('published'))
            for e in feed.entries]


def rippling(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://api.rippling.com/platform/api/ats/v1/board/{s}/jobs').json()
    out = []
    for j in data if isinstance(data, list) else []:
        loc = (j.get('workLocation') or {}).get('label') or _join(
            (j.get('workLocation') or {}).get('city'), (j.get('workLocation') or {}).get('country'))
        out.append(_job(j.get('name'), j.get('url'), company, loc,
                        _text(j.get('descriptionHtml') or j.get('description') or ''), j.get('createdAt')))
    return out


def pinpoint(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://{s}.pinpointhq.com/postings.json').json()
    out = []
    for j in data.get('data', []):
        loc = j.get('location') or {}
        out.append(_job(j.get('title'), j.get('url'), company,
                        loc.get('name') or _join(loc.get('city'), loc.get('province')),
                        _text(j.get('description', '')), j.get('published_at')))
    return out


def breezy(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://{s}.breezy.hr/json')
    out = []
    for j in data.json() if isinstance(data.json(), list) else []:
        loc = j.get('location') or {}
        where = loc.get('name') or _join(loc.get('city'), loc.get('state'),
                                         (loc.get('country') or {}).get('name'))
        if loc.get('is_remote'):
            where = _join(where, 'Remote')
        out.append(_job(j.get('name'), j.get('url') or f'https://{s}.breezy.hr/p/{j.get("id")}',
                        company, where, _text(j.get('description', '')), j.get('published_date')))
    return out


def _post(url, payload, timeout=TIMEOUT, headers=None):
    h = {'User-Agent': UA, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    h.update(headers or {})
    r = httpx.post(url, json=payload, timeout=timeout, follow_redirects=True, headers=h)
    r.raise_for_status()
    return r


def _host_and_path(url):
    p = urlparse(url if '//' in (url or '') else f'https://{url}')
    return (p.hostname or '').lower(), [s for s in (p.path or '').split('/') if s]


def workday(company, slug='', url=''):
    """Workday's public CXS endpoint: a paginated POST per career site.

    Addressed by careers URL rather than a slug, because a Workday board needs
    three parts — tenant, data-centre instance and site name — that only the
    URL carries (e.g. acme.wd5.myworkdayjobs.com/en-US/AcmeCareers).
    """
    host, segments = _host_and_path(url)
    if not host.endswith('myworkdayjobs.com') or not segments:
        raise ProviderError('Workday needs a careers URL like '
                            'https://acme.wd5.myworkdayjobs.com/en-US/CareerSite')
    tenant = host.split('.')[0]
    # The locale segment ("en-US") is optional and never the site name.
    site = next((s for s in reversed(segments) if not re.fullmatch(r'[a-z]{2}-[A-Z]{2}', s)), segments[-1])
    api = f'https://{host}/wday/cxs/{tenant}/{site}/jobs'
    job_base = f'https://{host}/{site}'
    out = []
    for page in range(5):  # 100 postings is plenty for a scan; deep pages risk the WAF
        data = _post(api, {'limit': 20, 'offset': page * 20, 'searchText': '',
                           'appliedFacets': {}}).json()
        postings = data.get('jobPostings') or []
        for j in postings:
            title, path = (j.get('title') or '').strip(), j.get('externalPath')
            if not title or not path:
                continue
            out.append(_job(title, job_base + path, company,
                            j.get('locationsText', ''), '', j.get('postedOn')))
        if len(postings) < 20:
            break
    return out


def bamboohr(company, slug='', url=''):
    tenant = _slug(slug) if slug else _host_and_path(url)[0].split('.')[0]
    origin = f'https://{tenant}.bamboohr.com'
    data = _get(f'{origin}/careers/list').json()
    out = []
    for j in data.get('result', []):
        title, jid = (j.get('jobOpeningName') or '').strip(), j.get('id')
        if not title or jid is None:
            continue
        loc = j.get('location') or {}
        where = _join(loc.get('city'), loc.get('state'))
        if j.get('isRemote'):
            where = _join(where, 'Remote')
        out.append(_job(title, f'{origin}/careers/{jid}', company, where, '',
                        j.get('datePosted')))
    return out


def oraclecloud(company, slug='', url=''):
    """Oracle Cloud HCM recruiting sites."""
    host, segments = _host_and_path(url)
    if not host:
        raise ProviderError('Oracle Cloud needs the careers URL')
    # The site number is the segment directly after "sites" in the career URL.
    site = segments[segments.index('sites') + 1] if 'sites' in segments[:-1] else 'CX'
    api = (f'https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions'
           f'?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber={site},'
           'limit=100,sortBy=POSTING_DATES_DESC')
    data = _get(api).json()
    out = []
    for item in data.get('items', []):
        for j in item.get('requisitionList', []):
            title, jid = (j.get('Title') or '').strip(), j.get('Id')
            if not title or not jid:
                continue
            out.append(_job(title,
                            f'https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}',
                            company, j.get('PrimaryLocation', ''), '', j.get('PostedDate')))
    return out


def eightfold(company, slug='', url=''):
    """Eightfold-hosted career sites."""
    host = _host_and_path(url)[0] or f'{_slug(slug)}.eightfold.ai'
    data = _get(f'https://{host}/api/apply/v2/jobs?domain={host}&start=0&num=100'
                '&sort_by=timestamp').json()
    out = []
    for j in data.get('positions', []):
        title = (j.get('name') or '').strip()
        link = j.get('canonicalPositionUrl') or j.get('positionUrl')
        if not title or not link:
            continue
        out.append(_job(title, link, company or j.get('company', ''),
                        j.get('location', ''), _text(j.get('job_description', '')),
                        j.get('t_create')))
    return out


def comeet(company, slug='', url=''):
    """Comeet needs a company UID and a public token, both in the board URL."""
    uid, token = '', ''
    if slug and '/' in slug:
        uid, token = slug.split('/', 1)
    elif slug:
        uid = slug
    if url and not token:
        m = re.search(r'company/([^/?]+).*?token=([^&]+)', url)
        if m:
            uid, token = m.group(1), m.group(2)
    if not uid or not token:
        raise ProviderError('Comeet needs "<company-uid>/<token>" as the slug')
    data = _get(f'https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={token}').json()
    return [_job(j.get('name'), j.get('url_active_page') or j.get('url_comeet_hosted_page'),
                 company, _join((j.get('location') or {}).get('city'),
                                (j.get('location') or {}).get('country')),
                 _text(str(j.get('details') or '')), j.get('time_updated'))
            for j in (data if isinstance(data, list) else []) if j.get('name')]


def getro(company, slug='', url=''):
    """Getro / VC talent-network collections."""
    cid = _slug(slug)
    data = _post(f'https://api.getro.com/api/v2/collections/{cid}/search/jobs',
                 {'hitsPerPage': 100, 'page': 0}).json()
    out = []
    for j in (data.get('results') or {}).get('jobs', data.get('jobs', [])):
        title, link = (j.get('title') or '').strip(), j.get('url')
        if not title or not link:
            continue
        org = j.get('organization') or {}
        out.append(_job(title, link, org.get('name') or company,
                        ', '.join(j.get('locations') or []) or j.get('location', ''),
                        _text(j.get('description', '')), j.get('created_at')))
    return out


def softgarden(company, slug='', url=''):
    tenant = _slug(slug) if slug else _host_and_path(url)[0].split('.')[0]
    data = _get(f'https://{tenant}.softgarden.io/api/rest/frontend/v3/jobs?limit=100').json()
    out = []
    for j in data.get('jobs', data if isinstance(data, list) else []):
        title = (j.get('jobTitle') or j.get('title') or '').strip()
        link = j.get('jobDetailUrl') or j.get('url')
        if not title or not link:
            continue
        out.append(_job(title, link, company, (j.get('location') or {}).get('city', '')
                        if isinstance(j.get('location'), dict) else j.get('location', ''),
                        _text(j.get('jobDescription', '')), j.get('onlineDate')))
    return out


def jobvite(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://jobs.jobvite.com/api/company/{s}/jobs').json()
    out = []
    for j in data.get('jobs', data if isinstance(data, list) else []):
        title = (j.get('title') or '').strip()
        jid = j.get('eId') or j.get('id')
        if not title or not jid:
            continue
        out.append(_job(title, j.get('applyUrl') or f'https://jobs.jobvite.com/{s}/job/{jid}',
                        company, j.get('location', ''), _text(j.get('description', '')),
                        j.get('postedDate')))
    return out


def join(company, slug='', url=''):
    s = _slug(slug)
    data = _get(f'https://join.com/api/public/companies/{s}/jobs').json()
    out = []
    for j in data.get('jobs', data if isinstance(data, list) else []):
        title = (j.get('title') or '').strip()
        jid = j.get('idParam') or j.get('id')
        if not title or not jid:
            continue
        out.append(_job(title, f'https://join.com/companies/{s}/jobs/{jid}', company,
                        _join((j.get('location') or {}).get('city') if isinstance(j.get('location'), dict)
                              else j.get('location'), 'Remote' if j.get('remote') else ''),
                        _text(j.get('description', '')), j.get('publishedAt')))
    return out


PROVIDERS = {
    'greenhouse': greenhouse, 'lever': lever, 'ashby': ashby,
    'smartrecruiters': smartrecruiters, 'workable': workable, 'recruitee': recruitee,
    'personio': personio, 'teamtailor': teamtailor, 'rippling': rippling,
    'pinpoint': pinpoint, 'breezy': breezy,
    'workday': workday, 'bamboohr': bamboohr, 'oraclecloud': oraclecloud,
    'eightfold': eightfold, 'comeet': comeet, 'getro': getro,
    'softgarden': softgarden, 'jobvite': jobvite, 'join': join,
}

#: Boards addressed by their careers URL rather than a short slug, because the
#: URL carries parts (tenant, instance, site) a slug cannot express.
URL_BASED = {'workday', 'oraclecloud', 'eightfold'}

#: Boards addressed by a slug on a shared host, vs. a slug in their own subdomain.
SLUG_HELP = {
    'greenhouse': 'board slug from boards.greenhouse.io/<slug>',
    'lever': 'company slug from jobs.lever.co/<slug>',
    'ashby': 'board slug from jobs.ashbyhq.com/<slug>',
    'smartrecruiters': 'company id from jobs.smartrecruiters.com/<slug>',
    'workable': 'account slug from apply.workable.com/<slug>',
    'recruitee': 'subdomain from <slug>.recruitee.com',
    'personio': 'subdomain from <slug>.jobs.personio.de',
    'teamtailor': 'subdomain from <slug>.teamtailor.com',
    'rippling': 'board slug from ats.rippling.com/<slug>',
    'pinpoint': 'subdomain from <slug>.pinpointhq.com',
    'breezy': 'subdomain from <slug>.breezy.hr',
    'workday': 'paste the full careers URL (tenant.wdN.myworkdayjobs.com/...)',
    'bamboohr': 'subdomain from <slug>.bamboohr.com',
    'oraclecloud': 'paste the full Oracle Cloud careers URL',
    'eightfold': 'paste the full Eightfold careers URL',
    'comeet': '"<company-uid>/<token>", both visible in the board URL',
    'getro': 'collection id from the Getro talent network',
    'softgarden': 'subdomain from <slug>.softgarden.io',
    'jobvite': 'company slug from jobs.jobvite.com/<slug>',
    'join': 'company slug from join.com/companies/<slug>',
}

# host pattern -> (provider id, how to pull the slug out of the URL)
_HOST_RULES = [
    (r'boards\.greenhouse\.io|job-boards\.greenhouse\.io', 'greenhouse', 'path'),
    (r'jobs\.lever\.co', 'lever', 'path'),
    (r'jobs\.ashbyhq\.com', 'ashby', 'path'),
    (r'(jobs|careers)\.smartrecruiters\.com', 'smartrecruiters', 'path'),
    (r'apply\.workable\.com', 'workable', 'path'),
    (r'ats\.rippling\.com', 'rippling', 'path'),
    (r'(.+)\.recruitee\.com', 'recruitee', 'subdomain'),
    (r'(.+)\.jobs\.personio\.(de|com)', 'personio', 'subdomain'),
    (r'(.+)\.teamtailor\.com', 'teamtailor', 'subdomain'),
    (r'(.+)\.pinpointhq\.com', 'pinpoint', 'subdomain'),
    (r'(.+)\.breezy\.hr', 'breezy', 'subdomain'),
    (r'(.+)\.bamboohr\.com', 'bamboohr', 'subdomain'),
    (r'(.+)\.softgarden\.io', 'softgarden', 'subdomain'),
    (r'jobs\.jobvite\.com', 'jobvite', 'path'),
    (r'join\.com', 'join', 'path-after-companies'),
    (r'.+\.wd\d+\.myworkdayjobs\.com', 'workday', 'url'),
    (r'.+\.eightfold\.ai|.+\.myeightfold\.ai', 'eightfold', 'url'),
    (r'.+\.oraclecloud\.com|.+\.fa\.[a-z0-9]+\.oraclecloud\.com', 'oraclecloud', 'url'),
    # detect() strips a leading "www.", so the bare host must be listed too.
    (r'comeet\.co|.+\.comeet\.co', 'comeet', 'comeet'),
]


def detect(url):
    """Work out the provider and slug from a careers URL.

    Returns ``(provider_id, slug)``, or ``(None, '')`` when the URL is an
    ordinary career page that only the generic crawler can handle.
    """
    if not url:
        return None, ''
    try:
        parsed = urlparse(url if '//' in url else f'https://{url}')
    except Exception:
        return None, ''
    host = (parsed.hostname or '').lower().removeprefix('www.')
    segments = [p for p in (parsed.path or '').split('/') if p]
    for pattern, provider, where in _HOST_RULES:
        m = re.fullmatch(pattern, host)
        if not m:
            continue
        if where == 'url':
            # The whole URL is the address; there is no meaningful short slug.
            return provider, ''
        if where == 'comeet':
            found = re.search(r'company/([^/?]+).*?token=([^&]+)', url)
            return provider, f'{found.group(1)}/{found.group(2)}' if found else ''
        if where == 'path-after-companies':
            idx = segments.index('companies') + 1 if 'companies' in segments else 0
            slug = segments[idx] if len(segments) > idx else ''
        elif where == 'subdomain':
            slug = m.group(1)
        else:
            slug = segments[0] if segments else ''
        # Greenhouse embed URLs carry the board under ?for=<slug>.
        if provider == 'greenhouse' and slug == 'embed':
            found = re.search(r'for=([A-Za-z0-9_-]+)', parsed.query or '')
            slug = found.group(1) if found else ''
        if slug and SLUG_RE.match(slug):
            return provider, slug
        return provider, ''
    return None, ''


def fetch(provider, company, slug='', url=''):
    """Run one provider adapter, raising ProviderError with a readable message."""
    fn = PROVIDERS.get(provider)
    if not fn:
        raise ProviderError(f'Unknown provider: {provider}')
    try:
        return fn(company, slug=slug, url=url)
    except ProviderError:
        raise
    except httpx.HTTPStatusError as e:
        raise ProviderError(f'{provider} returned HTTP {e.response.status_code} for "{slug}"') from e
    except Exception as e:
        raise ProviderError(f'{provider} fetch failed: {e}') from e
