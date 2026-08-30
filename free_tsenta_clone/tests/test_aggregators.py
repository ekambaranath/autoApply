"""Parser tests for the market-wide job sources.

Each source is exercised against a captured-shape payload with the HTTP layer
stubbed, so the suite verifies the parsing without touching the network.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import aggregators as A


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return json.loads(self._p) if isinstance(self._p, (str, bytes)) else self._p

    @property
    def text(self):
        return self._p if isinstance(self._p, str) else json.dumps(self._p)

    @property
    def content(self):
        return self._p.encode() if isinstance(self._p, str) else json.dumps(self._p).encode()


def _run(fn, payloads, **kwargs):
    """Serve payloads in order; the last one repeats for paginating sources."""
    queue = list(payloads)
    original = A._get
    A._get = lambda url, timeout=None, headers=None: _Resp(queue.pop(0) if len(queue) > 1 else queue[0])
    try:
        return fn(**kwargs)
    finally:
        A._get = original


def _one(jobs):
    assert len(jobs) >= 1, 'parser returned nothing'
    return jobs[0]


# --------------------------------------------------------------- helpers
def test_epoch_handles_seconds_millis_and_iso():
    assert A._epoch(1700000000).startswith('2023-11-14')
    assert A._epoch(1700000000000).startswith('2023-11-14')
    assert A._epoch('2026-05-01T10:00:00Z').startswith('2026-05-01')
    assert A._epoch('Mon, 01 May 2026 10:00:00 +0000').startswith('2026-05-01')
    assert A._epoch('') is None and A._epoch('not a date') is None


def test_first_skips_empty_values():
    assert A._first({'a': '', 'b': ' x '}, 'a', 'b') == 'x'
    assert A._first({}, 'a', default='fallback') == 'fallback'


def test_freshness_keeps_undated_rows():
    # Dropping undated rows would silently discard whole sources.
    assert A.is_fresh({'posted_at': None}, 30)
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert A.is_fresh({'posted_at': recent}, 30)
    assert not A.is_fresh({'posted_at': old}, 30)
    assert A.is_fresh({'posted_at': old}, 0)  # 0 disables the cutoff


# ----------------------------------------------------------- remote JSON
def test_remoteok_skips_the_legal_notice_row():
    payload = [{'legal': 'notice'},
               {'position': 'Backend Engineer', 'url': 'https://remoteok.com/l/1',
                'company': 'Acme', 'location': 'Worldwide', 'description': '<p>Build</p>',
                'epoch': 1700000000}]
    jobs = _run(A.remoteok, [payload])
    assert len(jobs) == 1
    j = jobs[0]
    assert j['title'] == 'Backend Engineer' and j['company'] == 'Acme'
    assert 'Remote' in j['location']


def test_remotive_parser():
    payload = {'jobs': [{'title': 'SRE', 'url': 'https://remotive.com/1',
                         'company_name': 'Globex', 'candidate_required_location': 'Europe',
                         'description': '<p>Run it</p>', 'publication_date': '2026-05-01T10:00:00'}]}
    j = _one(_run(A.remotive, [payload]))
    assert j['company'] == 'Globex' and j['description'] == 'Run it'
    assert j['posted_at'].startswith('2026-05-01')


def test_arbeitnow_appends_remote_and_converts_epoch_seconds():
    payload = {'data': [{'title': 'Data Engineer', 'url': 'https://arbeitnow.com/1',
                         'company_name': 'Initech', 'location': 'Berlin', 'remote': True,
                         'description': '<p>Pipelines</p>', 'created_at': 1700000000}]}
    j = _one(_run(A.arbeitnow, [payload]))
    assert j['location'] == 'Berlin, Remote'
    assert j['posted_at'].startswith('2023-11-14')


def test_himalayas_joins_location_restrictions():
    payload = {'jobs': [{'title': 'PM', 'applicationLink': 'https://h.app/1',
                         'companyName': 'Hooli', 'locationRestrictions': ['USA', 'Canada'],
                         'excerpt': 'Own it', 'pubDate': 1700000000}]}
    j = _one(_run(A.himalayas, [payload]))
    assert j['location'] == 'USA, Canada, Remote'


def test_workingnomads_parser():
    payload = [{'title': 'Designer', 'url': 'https://wn.com/1', 'company_name': 'Umbrella',
                'location': 'Anywhere', 'description': 'Design', 'pub_date': '2026-04-01'}]
    assert _one(_run(A.workingnomads, [payload]))['company'] == 'Umbrella'


def test_jobicy_parser():
    payload = {'jobs': [{'jobTitle': 'Analyst', 'url': 'https://jobicy.com/1',
                         'companyName': 'Acme', 'jobGeo': 'Anywhere',
                         'jobExcerpt': 'Analyse', 'pubDate': '2026-04-01 09:00:00'}]}
    j = _one(_run(A.jobicy, [payload]))
    assert j['title'] == 'Analyst' and j['posted_at'].startswith('2026-04-01')


def test_fourdayweek_accepts_bare_list_or_wrapped():
    row = {'title': 'Dev', 'url': 'https://4dw.io/1', 'company': 'Acme', 'location': 'UK'}
    assert _one(_run(A.fourdayweek, [[row]]))['title'] == 'Dev'
    assert _one(_run(A.fourdayweek, [{'jobs': [row]}]))['title'] == 'Dev'


def test_echojobs_parser():
    payload = [{'title': 'Rust Engineer', 'url': 'https://echojobs.io/1',
                'company': 'Globex', 'location': 'Remote'}]
    assert _one(_run(A.echojobs, [payload]))['company'] == 'Globex'


def test_themuse_reads_nested_landing_page():
    payload = {'results': [{'name': 'Marketer', 'refs': {'landing_page': 'https://muse/1'},
                            'company': {'name': 'Acme'}, 'locations': [{'name': 'NYC'}],
                            'contents': '<p>Market</p>', 'publication_date': '2026-03-01T00:00:00'}]}
    j = _one(_run(A.themuse, [payload]))
    assert j['url'] == 'https://muse/1' and j['location'] == 'NYC'


def test_getonbrd_reads_jsonapi_attributes():
    payload = {'data': [{'attributes': {
        'title': 'Backend Dev', 'public_url': 'https://getonbrd/1', 'city': 'Santiago',
        'description': 'Build', 'published_at': 1700000000,
        'company': {'data': {'attributes': {'name': 'Globex'}}}}}]}
    j = _one(_run(A.getonbrd, [payload]))
    assert j['company'] == 'Globex' and j['location'] == 'Santiago'


# ----------------------------------------------------------- Europe JSON
def test_justjoin_builds_url_from_slug():
    payload = [{'title': 'Java Dev', 'slug': 'java-dev-warsaw', 'companyName': 'Acme',
                'city': 'Warsaw', 'countryCode': 'PL', 'body': 'Code', 'publishedAt': '2026-05-01'}]
    j = _one(_run(A.justjoin, [payload]))
    assert j['url'] == 'https://justjoin.it/offers/java-dev-warsaw'
    assert j['location'] == 'Warsaw, PL'


def test_nofluffjobs_reads_nested_places():
    payload = {'postings': [{'title': 'Go Dev', 'id': 'abc', 'name': 'Acme',
                             'location': {'places': [{'city': 'Krakow'}], 'fullyRemote': False},
                             'posted': 1700000000}]}
    j = _one(_run(A.nofluffjobs, [payload]))
    assert j['url'].endswith('/job/abc') and j['location'] == 'Krakow'


def test_landingjobs_parser():
    payload = [{'title': 'Dev', 'url': 'https://landing.jobs/1', 'company_name': 'Acme',
                'city': 'Lisbon', 'country_name': 'Portugal', 'published_at': '2026-05-01'}]
    assert _one(_run(A.landingjobs, [payload]))['location'] == 'Lisbon, Portugal'


def test_manfred_builds_url_from_slug():
    payload = [{'position': 'Tech Lead', 'slug': 'tech-lead-1', 'company': {'name': 'Acme'},
                'descriptionHtml': '<p>Lead</p>', 'publicationDate': '2026-05-01'}]
    j = _one(_run(A.manfred, [payload]))
    assert j['url'].endswith('/ofertas-empleo/tech-lead-1') and j['description'] == 'Lead'


def test_thehub_parser():
    payload = {'docs': [{'title': 'Founder Engineer', '_id': 'xyz',
                         'company': {'name': 'Nordic Co'}, 'description': 'Build',
                         'createdAt': '2026-05-01T00:00:00Z'}]}
    j = _one(_run(A.thehub, [payload]))
    assert j['url'].endswith('/jobs/xyz') and j['company'] == 'Nordic Co'


def test_arbeitsagentur_parser():
    payload = {'stellenangebote': [{'titel': 'Softwareentwickler', 'refnr': '123-abc',
                                    'arbeitgeber': 'Acme GmbH',
                                    'arbeitsort': {'ort': 'Berlin', 'region': 'Berlin'},
                                    'aktuelleVeroeffentlichungsdatum': '2026-05-01'}]}
    j = _one(_run(A.arbeitsagentur, [payload]))
    assert j['url'].endswith('/jobdetail/123-abc') and j['company'] == 'Acme GmbH'


def test_solidjobs_parser():
    payload = [{'title': 'QA', 'id': 42, 'companyName': 'Acme', 'city': 'Bucharest',
                'description': 'Test', 'publishedDate': '2026-05-01'}]
    assert _one(_run(A.solidjobs, [payload]))['company'] == 'Acme'


# ------------------------------------------------------------- APAC JSON
def test_mycareersfuture_parser():
    payload = {'results': [{'title': 'Engineer', 'uuid': 'u1',
                            'metadata': {'jobPostId': 'u1', 'originalPostingDate': '2026-05-01'},
                            'postedCompany': {'name': 'Acme Pte'},
                            'addresses': [{'address': {'name': 'Singapore'}}],
                            'description': '<p>Build</p>'}]}
    j = _one(_run(A.mycareersfuture, [payload]))
    assert j['company'] == 'Acme Pte' and j['url'].endswith('/job/u1')


def test_yourator_parser():
    payload = {'payload': {'jobs': [{'name': 'Frontend', 'path': '/companies/acme/jobs/1',
                                     'company': {'brand_name': 'Acme'},
                                     'created_at': '2026-05-01'}]}}
    j = _one(_run(A.yourator, [payload]))
    assert j['url'] == 'https://www.yourator.co/companies/acme/jobs/1'


def test_jobstreet_parser():
    payload = {'data': [{'title': 'Analyst', 'id': '99',
                         'advertiser': {'description': 'Acme'},
                         'locations': [{'label': 'Jakarta'}], 'teaser': 'Analyse',
                         'listingDate': '2026-05-01'}]}
    j = _one(_run(A.jobstreet, [payload]))
    assert j['location'] == 'Jakarta' and j['url'].endswith('/job/99')


# ------------------------------------------------------------------ RSS
RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Acme: Senior Engineer</title><link>https://example.com/j/1</link>
<description>&lt;p&gt;Build things&lt;/p&gt;</description>
<pubDate>Mon, 01 May 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_rss_splits_company_from_title():
    j = _one(_run(A.weworkremotely, [RSS]))
    assert j['company'] == 'Acme' and j['title'] == 'Senior Engineer'
    assert j['description'] == 'Build things'
    assert j['posted_at'].startswith('2026-05-01')


def test_rss_sources_all_parse():
    for fn in (A.nodesk, A.cryptocurrencyjobs, A.larajobs, A.jobbankca, A.higheredjobs):
        assert len(_run(fn, [RSS])) == 1, fn.__name__


def test_rss_drops_items_missing_a_link():
    broken = RSS.replace('<link>https://example.com/j/1</link>', '')
    assert _run(A.weworkremotely, [broken]) == []


# ------------------------------------------------------------------- HN
def test_hackernews_reads_the_current_thread():
    search = {'hits': [{'objectID': '111', 'title': 'Ask HN: Who is hiring? (May 2026)'}]}
    item = {'children': [
        {'id': 1, 'created_at': '2026-05-01T00:00:00Z',
         'text': 'Acme | Senior Engineer | Berlin | REMOTE<p>We build things and need help. '
                 'Long enough to clear the minimum body length used to skip chatter.</p>'},
        {'id': 2, 'text': 'too short'},
    ]}
    jobs = _run(A.hackernews, [search, item])
    assert len(jobs) == 1
    assert jobs[0]['company'] == 'Acme'
    assert jobs[0]['url'].endswith('id=1')


def test_hackernews_returns_nothing_without_a_thread():
    assert _run(A.hackernews, [{'hits': [{'objectID': '1', 'title': 'Ask HN: Who wants to be hired?'}]}]) == []


# -------------------------------------------------------------- registry
def test_every_registered_source_is_callable_and_documented():
    assert len(A.AGGREGATORS) >= 25
    for sid, (fn, label, coverage) in A.AGGREGATORS.items():
        assert callable(fn), sid
        assert label and coverage, sid


def test_defaults_are_all_real_sources():
    for sid in A.DEFAULT_ENABLED:
        assert sid in A.AGGREGATORS, sid


def test_unknown_source_raises():
    try:
        A.fetch('nope')
    except Exception as e:
        assert 'Unknown source' in str(e)
    else:
        raise AssertionError('expected an error')


def test_rows_without_title_or_url_are_dropped():
    payload = {'jobs': [{'title': '', 'url': 'https://x/1'},
                        {'title': 'Real', 'url': ''},
                        {'title': 'Keeper', 'url': 'https://x/2', 'company_name': 'Acme'}]}
    jobs = _run(A.remotive, [payload])
    assert [j['title'] for j in jobs] == ['Keeper']


if __name__ == '__main__':
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                passed += 1
            except Exception as exc:
                failed += 1
                print(f'FAIL {name}: {type(exc).__name__}: {exc}')
    print(f'\n{passed} passed, {failed} failed')
    sys.exit(1 if failed else 0)
