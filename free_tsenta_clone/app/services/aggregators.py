"""Market-wide job sources that need no watchlist.

Endpoint map adapted from career-ops (MIT, (c) 2026 Santiago Fernandez de
Valderrama) — its `providers/` directory. https://github.com/santifer/career-ops

An ATS adapter in `providers.py` answers "what is *this company* hiring for?"
and needs a board slug. An aggregator answers "what has *anyone* posted
lately?" and needs nothing but your keywords — which is what keeps a steady
supply of genuinely fresh postings coming in.

Every adapter has the same shape:

    fn(query: str, location: str, limit: int) -> list[job dicts]

Third-party feeds rename fields without warning, so each parser reads through a
list of candidate keys and drops a row it cannot make a title and URL from,
rather than failing the whole source.
"""
import re
from datetime import datetime, timedelta, timezone

from .providers import _get, _text, _job, _join, ProviderError

RSS_TIMEOUT = 30


# ------------------------------------------------------------- utilities
def _first(d, *keys, default=''):
    """First non-empty value among `keys`, so a renamed field degrades softly."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and v:
            return v
    return default


def _epoch(value):
    """Normalize the several date shapes these feeds use to ISO-8601."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        # Seconds vs milliseconds: anything past ~2001 in ms is > 1e12.
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _epoch(int(text))
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).isoformat()
    except ValueError:
        pass
    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            d = datetime.strptime(text, fmt)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
        except ValueError:
            continue
    return None


def _matches(job, query):
    """Client-side keyword filter for feeds with no server-side search."""
    if not query:
        return True
    terms = [t.strip().lower() for t in re.split(r'[,\n]', query) if t.strip()]
    if not terms:
        return True
    hay = f'{job["title"]} {job["description"]} {job["company"]}'.lower()
    return any(t in hay for t in terms)


def _rss(url, company_from='author', default_company=''):
    """Shared RSS reader — several boards publish nothing but a feed."""
    import feedparser
    feed = feedparser.parse(_get(url, timeout=RSS_TIMEOUT).text)
    out = []
    for e in feed.entries:
        title = (e.get('title') or '').strip()
        link = (e.get('link') or '').strip()
        if not title or not link:
            continue
        company = (e.get(company_from) or '').strip() or default_company
        # "Company: Role" is the near-universal convention in job RSS titles.
        if not company and ':' in title:
            company, title = [p.strip() for p in title.split(':', 1)]
        out.append(_job(title, link, company, e.get('location', ''),
                        _text(e.get('summary') or e.get('description') or ''),
                        _epoch(e.get('published') or e.get('updated'))))
    return out


# ------------------------------------------------------- remote-first JSON
def remoteok(query='', location='', limit=100):
    # The first element is a legal notice, not a posting.
    rows = _get('https://remoteok.com/api').json()
    out = []
    for j in rows[1:] if isinstance(rows, list) else []:
        if not isinstance(j, dict):
            continue
        title = _first(j, 'position', 'title')
        url = _first(j, 'url', 'apply_url')
        if not title or not url:
            continue
        out.append(_job(title, url, _first(j, 'company', default='RemoteOK'),
                        _join(_first(j, 'location'), 'Remote'),
                        _text(_first(j, 'description')), _epoch(j.get('epoch') or j.get('date'))))
    return out[:limit]


def remotive(query='', location='', limit=100):
    url = 'https://remotive.com/api/remote-jobs?limit=200'
    if query:
        url += f'&search={query.split(",")[0].strip()}'
    data = _get(url).json()
    return [_job(_first(j, 'title'), _first(j, 'url'), _first(j, 'company_name', default='Remotive'),
                 _join(_first(j, 'candidate_required_location'), 'Remote'),
                 _text(_first(j, 'description')), _epoch(j.get('publication_date')))
            for j in data.get('jobs', []) if _first(j, 'title') and _first(j, 'url')][:limit]


def arbeitnow(query='', location='', limit=100):
    data = _get('https://www.arbeitnow.com/api/job-board-api').json()
    out = []
    for j in data.get('data', []):
        title, url = _first(j, 'title'), _first(j, 'url')
        if not title or not url:
            continue
        where = _first(j, 'location')
        if j.get('remote'):
            where = _join(where, 'Remote')
        out.append(_job(title, url, _first(j, 'company_name', default='Arbeitnow'), where,
                        _text(_first(j, 'description')), _epoch(j.get('created_at'))))
    return out[:limit]


def himalayas(query='', location='', limit=100):
    data = _get(f'https://himalayas.app/jobs/api?limit={min(limit, 100)}').json()
    out = []
    for j in data.get('jobs', []):
        title, url = _first(j, 'title'), _first(j, 'applicationLink', 'url')
        if not title or not url:
            continue
        restrictions = j.get('locationRestrictions')
        where = ', '.join(restrictions) if isinstance(restrictions, list) else _first(j, 'location')
        out.append(_job(title, url, _first(j, 'companyName', default='Himalayas'),
                        _join(where, 'Remote'), _text(_first(j, 'description', 'excerpt')),
                        _epoch(j.get('pubDate') or j.get('publishedDate'))))
    return out[:limit]


def workingnomads(query='', location='', limit=100):
    rows = _get('https://www.workingnomads.com/api/exposed_jobs/').json()
    return [_job(_first(j, 'title'), _first(j, 'url'),
                 _first(j, 'company_name', default='Working Nomads'),
                 _join(_first(j, 'location'), 'Remote'),
                 _text(_first(j, 'description')), _epoch(j.get('pub_date')))
            for j in (rows if isinstance(rows, list) else [])
            if _first(j, 'title') and _first(j, 'url')][:limit]


def jobicy(query='', location='', limit=100):
    data = _get(f'https://jobicy.com/api/v2/remote-jobs?count={min(limit, 50)}').json()
    return [_job(_first(j, 'jobTitle', 'title'), _first(j, 'url'),
                 _first(j, 'companyName', default='Jobicy'),
                 _join(_first(j, 'jobGeo'), 'Remote'),
                 _text(_first(j, 'jobDescription', 'jobExcerpt')), _epoch(j.get('pubDate')))
            for j in data.get('jobs', []) if _first(j, 'jobTitle', 'title')][:limit]


def fourdayweek(query='', location='', limit=100):
    """Roles at companies on a four-day week."""
    data = _get('https://4dayweek.io/api/jobs').json()
    rows = data if isinstance(data, list) else data.get('jobs', [])
    return [_job(_first(j, 'title', 'position'), _first(j, 'url', 'link'),
                 _first(j, 'company', 'company_name', default='4dayweek'),
                 _first(j, 'location'), _text(_first(j, 'description')),
                 _epoch(j.get('created_at') or j.get('date')))
            for j in rows if _first(j, 'title', 'position') and _first(j, 'url', 'link')][:limit]


def echojobs(query='', location='', limit=100):
    data = _get('https://echojobs.io/api/jobs').json()
    rows = data if isinstance(data, list) else data.get('jobs', [])
    return [_job(_first(j, 'title'), _first(j, 'url', 'applyUrl'),
                 _first(j, 'company', 'companyName', default='EchoJobs'),
                 _first(j, 'location'), _text(_first(j, 'description')),
                 _epoch(j.get('postedAt') or j.get('createdAt')))
            for j in rows if _first(j, 'title')][:limit]


def themuse(query='', location='', limit=100):
    out = []
    for page in range(2):
        url = f'https://www.themuse.com/api/public/jobs?page={page}'
        if location:
            url += f'&location={location.split(",")[0].strip()}'
        for j in _get(url).json().get('results', []):
            title = _first(j, 'name', 'title')
            link = ((j.get('refs') or {}).get('landing_page') or '')
            if not title or not link:
                continue
            where = ', '.join(x.get('name', '') for x in (j.get('locations') or []))
            out.append(_job(title, link, (j.get('company') or {}).get('name', 'The Muse'),
                            where, _text(_first(j, 'contents')), _epoch(j.get('publication_date'))))
    return out[:limit]


def getonbrd(query='', location='', limit=100):
    """Latin-American tech roles."""
    term = (query.split(',')[0].strip() or 'engineer')
    data = _get(f'https://www.getonbrd.com/api/v0/search/jobs?query={term}&per_page={min(limit, 50)}').json()
    out = []
    for j in data.get('data', []):
        attrs = j.get('attributes') or {}
        title, link = _first(attrs, 'title'), _first(attrs, 'public_url')
        if not title or not link:
            continue
        company = ((attrs.get('company') or {}).get('data') or {}).get('attributes', {}).get('name', '')
        out.append(_job(title, link, company or 'Get on Board',
                        _first(attrs, 'city', 'country'), _text(_first(attrs, 'description')),
                        _epoch(attrs.get('published_at'))))
    return out[:limit]


# ------------------------------------------------------------- Europe JSON
def justjoin(query='', location='', limit=100):
    """Polish tech market."""
    rows = _get('https://justjoin.it/api/candidate-api/offers').json()
    out = []
    for j in (rows if isinstance(rows, list) else rows.get('data', [])):
        title, slug = _first(j, 'title'), _first(j, 'slug')
        if not title or not slug:
            continue
        out.append(_job(title, f'https://justjoin.it/offers/{slug}',
                        _first(j, 'companyName', default='JustJoin.it'),
                        _join(_first(j, 'city'), _first(j, 'countryCode')),
                        _text(_first(j, 'body')), _epoch(j.get('publishedAt'))))
    return out[:limit]


def nofluffjobs(query='', location='', limit=100):
    data = _get('https://nofluffjobs.com/api/search/posting?limit=200').json()
    out = []
    for j in data.get('postings', []):
        title, url_key = _first(j, 'title', 'name'), _first(j, 'url', 'id')
        if not title or not url_key:
            continue
        loc = j.get('location') or {}
        places = ', '.join(p.get('city', '') for p in (loc.get('places') or []) if p.get('city'))
        out.append(_job(title, f'https://nofluffjobs.com/job/{url_key}',
                        _first(j, 'name', default='') or (j.get('company') or {}).get('name', 'NoFluffJobs'),
                        places or ('Remote' if loc.get('fullyRemote') else ''),
                        '', _epoch(j.get('posted'))))
    return out[:limit]


def landingjobs(query='', location='', limit=100):
    rows = _get(f'https://landing.jobs/api/v1/jobs?limit={min(limit, 100)}').json()
    return [_job(_first(j, 'title'), _first(j, 'url'),
                 _first(j, 'company_name', default='Landing.jobs'),
                 _join(_first(j, 'city'), _first(j, 'country_name')),
                 _text(_first(j, 'description')), _epoch(j.get('published_at')))
            for j in (rows if isinstance(rows, list) else [])
            if _first(j, 'title') and _first(j, 'url')][:limit]


def manfred(query='', location='', limit=100):
    """Spanish tech market."""
    rows = _get('https://www.getmanfred.com/api/v2/public/offers').json()
    out = []
    for j in (rows if isinstance(rows, list) else []):
        title, slug = _first(j, 'position', 'title'), _first(j, 'slug')
        if not title:
            continue
        link = f'https://www.getmanfred.com/ofertas-empleo/{slug}' if slug else _first(j, 'url')
        if not link:
            continue
        out.append(_job(title, link, (j.get('company') or {}).get('name', 'Manfred'),
                        _first(j, 'location') or 'Spain',
                        _text(_first(j, 'descriptionHtml', 'description')),
                        _epoch(j.get('publicationDate'))))
    return out[:limit]


def thehub(query='', location='', limit=100):
    """Nordic startup jobs."""
    data = _get('https://thehub.io/api/v2/jobsandfeatured?limit=200').json()
    rows = data.get('docs') or data.get('jobs') or (data if isinstance(data, list) else [])
    out = []
    for j in rows:
        title, jid = _first(j, 'title'), _first(j, '_id', 'id')
        if not title or not jid:
            continue
        out.append(_job(title, f'https://thehub.io/jobs/{jid}',
                        (j.get('company') or {}).get('name', 'The Hub'),
                        _first(j, 'location') or 'Nordics',
                        _text(_first(j, 'description')), _epoch(j.get('createdAt'))))
    return out[:limit]


def arbeitsagentur(query='', location='', limit=100):
    """Germany's federal employment agency."""
    term = (query.split(',')[0].strip() or 'software')
    url = ('https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs'
           f'?was={term}&size={min(limit, 100)}&page=1')
    if location:
        url += f'&wo={location.split(",")[0].strip()}'
    # This API requires a fixed public client key, published in its own docs.
    data = _get(url, headers={'X-API-Key': 'jobboerse-jobsuche'}).json()
    out = []
    for j in data.get('stellenangebote', []):
        title, ref = _first(j, 'titel', 'beruf'), _first(j, 'refnr')
        if not title or not ref:
            continue
        out.append(_job(title, f'https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}',
                        _first(j, 'arbeitgeber', default='Arbeitsagentur'),
                        _join((j.get('arbeitsort') or {}).get('ort'),
                              (j.get('arbeitsort') or {}).get('region')),
                        '', _epoch(j.get('aktuelleVeroeffentlichungsdatum'))))
    return out[:limit]


def solidjobs(query='', location='', limit=100):
    rows = _get('https://solid.jobs/public-api/offers/it').json()
    return [_job(_first(j, 'title', 'name'), _first(j, 'url') or
                 f'https://solid.jobs/offers/it/{_first(j, "id")}',
                 _first(j, 'companyName', 'company', default='SolidJobs'),
                 _first(j, 'city', 'location'), _text(_first(j, 'description')),
                 _epoch(j.get('publishedDate') or j.get('addedDate')))
            for j in (rows if isinstance(rows, list) else [])
            if _first(j, 'title', 'name')][:limit]


# --------------------------------------------------------------- APAC JSON
def mycareersfuture(query='', location='', limit=100):
    """Singapore's government job portal."""
    term = (query.split(',')[0].strip() or 'engineer')
    data = _get(f'https://api.mycareersfuture.gov.sg/v2/search?search={term}'
                f'&limit={min(limit, 100)}&page=0').json()
    out = []
    for j in data.get('results', []):
        meta = j.get('metadata') or {}
        title, uuid = _first(j, 'title'), _first(meta, 'jobPostId') or _first(j, 'uuid')
        if not title or not uuid:
            continue
        out.append(_job(title, f'https://www.mycareersfuture.gov.sg/job/{uuid}',
                        ((j.get('postedCompany') or {}).get('name') or 'MyCareersFuture'),
                        ', '.join(a.get('address', {}).get('name', '')
                                  for a in (j.get('addresses') or [])) or 'Singapore',
                        _text(_first(j, 'description')), _epoch(meta.get('originalPostingDate'))))
    return out[:limit]


def yourator(query='', location='', limit=100):
    """Taiwan startup jobs."""
    data = _get(f'https://www.yourator.co/api/v4/jobs?page=1&per_page={min(limit, 100)}').json()
    out = []
    for j in data.get('payload', {}).get('jobs', data.get('jobs', [])):
        title, path = _first(j, 'name', 'title'), _first(j, 'path', 'url')
        if not title or not path:
            continue
        link = path if path.startswith('http') else f'https://www.yourator.co{path}'
        out.append(_job(title, link, (j.get('company') or {}).get('brand_name', 'Yourator'),
                        _first(j, 'location') or 'Taiwan', _text(_first(j, 'description')),
                        _epoch(j.get('created_at'))))
    return out[:limit]


def jobstreet(query='', location='', limit=100):
    """SEA market via the SEEK-family search API."""
    term = (query.split(',')[0].strip() or 'engineer')
    data = _get('https://id.jobstreet.com/api/jobsearch/v5/search'
                f'?keywords={term}&pageSize={min(limit, 100)}&page=1&siteKey=ID-Main'
                '&sourcesystem=houston').json()
    out = []
    for j in data.get('data', []):
        title, jid = _first(j, 'title'), _first(j, 'id')
        if not title or not jid:
            continue
        out.append(_job(title, f'https://id.jobstreet.com/job/{jid}',
                        (j.get('advertiser') or {}).get('description', 'JobStreet'),
                        (j.get('locations') or [{}])[0].get('label', ''),
                        _text(_first(j, 'teaser')), _epoch(j.get('listingDate'))))
    return out[:limit]


# ---------------------------------------------------------------- RSS/feeds
def weworkremotely(query='', location='', limit=100):
    return _rss('https://weworkremotely.com/remote-jobs.rss', default_company='')[:limit]


def nodesk(query='', location='', limit=100):
    return _rss('https://nodesk.co/remote-jobs/index.xml', default_company='NODESK')[:limit]


def cryptocurrencyjobs(query='', location='', limit=100):
    return _rss('https://cryptocurrencyjobs.co/index.xml', default_company='')[:limit]


def larajobs(query='', location='', limit=100):
    """PHP / Laravel roles."""
    return _rss('https://larajobs.com/feed', default_company='LaraJobs')[:limit]


def jobbankca(query='', location='', limit=100):
    """Canada's federal job bank."""
    term = (query.split(',')[0].strip() or 'developer').replace(' ', '+')
    return _rss('https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed'
                f'?searchstring={term}', default_company='')[:limit]


def higheredjobs(query='', location='', limit=100):
    """Academic and university roles."""
    return _rss('https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=32',
                default_company='')[:limit]


def hackernews(query='', location='', limit=100):
    """Top-level comments on the current "Ask HN: Who is hiring?" thread.

    Each comment is one opening written in prose, so there is no structured
    title. The first line is the closest thing, which is why the whole comment
    is kept as the description for scoring to work on.
    """
    search = _get('https://hn.algolia.com/api/v1/search_by_date'
                  '?tags=story,author_whoishiring&query=hiring&hitsPerPage=3').json()
    stories = [h for h in search.get('hits', []) if 'who is hiring' in (h.get('title') or '').lower()]
    if not stories:
        return []
    item = _get(f'https://hn.algolia.com/api/v1/items/{stories[0]["objectID"]}').json()
    out = []
    for c in (item.get('children') or [])[:limit]:
        body = _text(c.get('text') or '')
        if not body or len(body) < 80:
            continue
        headline = body.split('\n')[0][:180]
        out.append(_job(headline, f'https://news.ycombinator.com/item?id={c.get("id")}',
                        headline.split('|')[0].strip()[:80], '', body, _epoch(c.get('created_at'))))
    return out


#: id -> (function, human label, coverage note)
AGGREGATORS = {
    'remoteok': (remoteok, 'RemoteOK', 'Remote, global'),
    'remotive': (remotive, 'Remotive', 'Remote, global'),
    'arbeitnow': (arbeitnow, 'Arbeitnow', 'Europe, remote-friendly'),
    'himalayas': (himalayas, 'Himalayas', 'Remote, global'),
    'workingnomads': (workingnomads, 'Working Nomads', 'Remote, global'),
    'jobicy': (jobicy, 'Jobicy', 'Remote, global'),
    'fourdayweek': (fourdayweek, '4 Day Week', 'Four-day-week employers'),
    'echojobs': (echojobs, 'EchoJobs', 'Software engineering'),
    'themuse': (themuse, 'The Muse', 'US, general'),
    'getonbrd': (getonbrd, 'Get on Board', 'Latin America'),
    'justjoin': (justjoin, 'JustJoin.it', 'Poland, tech'),
    'nofluffjobs': (nofluffjobs, 'NoFluffJobs', 'Poland/CEE, tech'),
    'landingjobs': (landingjobs, 'Landing.jobs', 'Portugal/Europe, tech'),
    'manfred': (manfred, 'Manfred', 'Spain, tech'),
    'thehub': (thehub, 'The Hub', 'Nordics, startups'),
    'arbeitsagentur': (arbeitsagentur, 'Arbeitsagentur', 'Germany, all sectors'),
    'solidjobs': (solidjobs, 'SolidJobs', 'Romania, IT'),
    'mycareersfuture': (mycareersfuture, 'MyCareersFuture', 'Singapore'),
    'yourator': (yourator, 'Yourator', 'Taiwan, startups'),
    'jobstreet': (jobstreet, 'JobStreet', 'Southeast Asia'),
    'weworkremotely': (weworkremotely, 'We Work Remotely', 'Remote, global'),
    'nodesk': (nodesk, 'NODESK', 'Remote, global'),
    'cryptocurrencyjobs': (cryptocurrencyjobs, 'Cryptocurrency Jobs', 'Crypto/web3'),
    'larajobs': (larajobs, 'LaraJobs', 'PHP / Laravel'),
    'jobbankca': (jobbankca, 'Job Bank Canada', 'Canada, all sectors'),
    'higheredjobs': (higheredjobs, 'HigherEdJobs', 'Academia'),
    'hackernews': (hackernews, 'HN Who is hiring', 'Startups, monthly thread'),
}

#: Sensible starting set — broad, English-language and genuinely high volume.
DEFAULT_ENABLED = ['remoteok', 'remotive', 'arbeitnow', 'himalayas', 'workingnomads',
                   'weworkremotely', 'jobicy', 'hackernews']


def fetch(source, query='', location='', limit=100):
    entry = AGGREGATORS.get(source)
    if not entry:
        raise ProviderError(f'Unknown source: {source}')
    try:
        jobs = entry[0](query=query, location=location, limit=limit)
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f'{source} fetch failed: {e}') from e
    return [j for j in jobs if j.get('title') and j.get('url')]


def is_fresh(job, max_age_days):
    """Whether a posting is recent enough to be worth surfacing.

    A feed that omits its posting date is treated as fresh: dropping every
    undated row would silently discard whole sources, which is worse than
    showing something slightly stale.
    """
    if not max_age_days:
        return True
    posted = job.get('posted_at')
    if not posted:
        return True
    try:
        when = datetime.fromisoformat(str(posted).replace('Z', '+00:00'))
    except ValueError:
        return True
    if not when.tzinfo:
        when = when.replace(tzinfo=timezone.utc)
    return when >= datetime.now(timezone.utc) - timedelta(days=max_age_days)
