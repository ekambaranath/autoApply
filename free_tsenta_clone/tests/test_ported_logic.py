"""Tests for the logic ported from career-ops plus the ATS provider parsers.

The provider tests stub the HTTP layer with captured response shapes, so the
parsers are verified without reaching the network.

Run: python -m pytest tests/ -q     (or: python tests/test_ported_logic.py)
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import providers as P
from app.services.insights import (channel_rates, detect_reposts, followups,
                                   legitimacy_signals)
from app.services.role_match import (role_fuzzy_match, role_tokens,
                                     title_identity_key)
from app.services.states import compare_lifecycle, fold, is_terminal
from app.services.title_filter import build_title_filter, compile_keyword


# ------------------------------------------------------------ role match
def test_identical_titles_always_match():
    assert role_fuzzy_match('Member of Technical Staff', 'Member of Technical Staff')


def test_specialization_suffix_keeps_titles_distinct():
    assert not role_fuzzy_match('Senior Analytics Engineer',
                                'Senior Analytics Engineer, People Analytics')


def test_sub_baseline_seniority_is_a_disagreement():
    assert not role_fuzzy_match('Associate Product Manager, Team', 'Product Manager, Team')


def test_conflicting_seniority_never_matches():
    assert not role_fuzzy_match('Senior Backend Engineer', 'Principal Backend Engineer')


def test_baseline_only_overlap_is_not_a_match():
    assert not role_fuzzy_match('Software Engineer', 'Product Engineer')


def test_dropped_seniority_still_matches():
    assert role_fuzzy_match('Senior Kubernetes Platform Engineer',
                            'Kubernetes Platform Engineer')


def test_accent_folding():
    assert role_fuzzy_match('Sênior Kubernetes Engineer', 'Senior Kubernetes Engineer')


def test_slashed_acronym_survives_tokenizing():
    assert 'cicd' in role_tokens('Senior SWE, Infrastructure (CI/CD)')


def test_title_identity_key_is_order_insensitive():
    assert title_identity_key('Backend Engineer, Payments') == \
           title_identity_key('Payments — Engineer Backend')


# ---------------------------------------------------------- title filter
def test_word_prefix_anchors_both_sides():
    f = build_title_filter(negative=['word:intern'])
    assert not f('Operations Intern')
    assert f('Internal Tools Engineer')
    assert f('International Partnerships Manager')


def test_stem_prefix_anchors_the_left_side_only():
    f = build_title_filter(positive=['stem:agent'])
    assert f('Agentforce Developer')
    assert f('Agentic AI Engineer')
    assert not f('Reagents Chemist')


def test_and_group_requires_every_term():
    f = build_title_filter(positive=['director + engineering'])
    assert f('Senior Director, Platform Engineering')
    assert not f('Director of Marketing')


def test_short_acronyms_anchor_automatically():
    coo = compile_keyword('coo')
    assert not coo('coordinator')
    assert coo('chief coo')


def test_empty_positive_means_no_constraint():
    assert build_title_filter(positive=[])('anything at all')


def test_bare_prefix_matches_nothing_rather_than_everything():
    assert not build_title_filter(positive=['word:'])('anything at all')


# ---------------------------------------------------------------- states
def test_aliases_fold_to_canonical_ids():
    assert fold('applied') == 'SUBMITTED'
    assert fold('Ready For Review') == 'READY_FOR_REVIEW'
    assert fold('replied') == 'RESPONDED'


def test_unknown_status_is_preserved_not_dropped():
    assert fold('some_new_state') == 'SOME_NEW_STATE'


def test_lifecycle_ordering_and_terminals():
    assert compare_lifecycle('SUBMITTED', 'INTERVIEW') < 0
    assert compare_lifecycle('OFFER', 'REJECTED') == 0
    assert is_terminal('rejected') and not is_terminal('applied')


# --------------------------------------------------------------- reposts
def _job(jid, company, title, url, day):
    return {'id': jid, 'company': company, 'title': title, 'url': url,
            'created_at': f'2026-03-{day:02d}T00:00:00+00:00'}


def test_repost_cluster_needs_two_distinct_urls():
    same_url = [_job('1', 'Acme', 'Data Engineer', 'https://a.co/1', 1),
                _job('2', 'Acme', 'Data Engineer', 'https://a.co/1', 20)]
    assert detect_reposts(same_url) == []


def test_same_day_listings_are_concurrent_reqs_not_reposts():
    concurrent = [_job('1', 'Acme', 'Data Engineer', 'https://a.co/1', 5),
                  _job('2', 'Acme', 'Data Engineer', 'https://a.co/2', 5)]
    assert detect_reposts(concurrent) == []


def test_relisting_at_a_new_url_is_detected():
    rows = [_job('1', 'Acme', 'Data Engineer', 'https://a.co/1', 1),
            _job('2', 'Acme', 'Engineer Data', 'https://a.co/2', 20)]
    clusters = detect_reposts(rows)
    assert len(clusters) == 1
    assert clusters[0]['repost_count'] == 2
    assert clusters[0]['days_span'] == 19


def test_sightings_outside_the_window_are_not_one_cluster():
    rows = [_job('1', 'Acme', 'Data Engineer', 'https://a.co/1', 1),
            _job('2', 'Acme', 'Data Engineer', 'https://a.co/2', 20)]
    assert detect_reposts(rows, window_days=5) == []


# ------------------------------------------------------------ legitimacy
def test_upfront_fee_is_critical():
    res = legitimacy_signals({'company': 'X', 'description': 'x' * 500 +
                              ' You must pay a training fee before starting.'})
    assert res['level'] == 'caution'
    assert any(f['code'] == 'asks_for_money' for f in res['flags'])


def test_clean_posting_only_raises_soft_notices():
    good = {'company': 'Acme', 'description': (
        'We are hiring a backend engineer. ' * 30 + ' Salary: $150,000 - $190,000.')}
    res = legitimacy_signals(good)
    assert res['level'] in ('clear', 'notice')
    assert not any(f['severity'] in ('critical', 'serious') for f in res['flags'])


def test_missing_salary_and_thin_body_are_notices():
    codes = {f['code'] for f in legitimacy_signals({'company': 'Acme', 'description': 'Short.'})['flags']}
    assert {'thin_description', 'no_salary'} <= codes


def test_repost_count_raises_a_ghost_job_flag():
    res = legitimacy_signals({'company': 'Acme', 'description': 'x' * 900}, repost_count=4)
    assert any(f['code'] == 'frequently_reposted' for f in res['flags'])


# -------------------------------------------------------------- followups
def test_submitted_application_becomes_due_after_the_cadence():
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    apps = [{'id': 'a', 'status': 'SUBMITTED', 'title': 'Dev', 'company': 'Acme',
             'updated_at': (now - timedelta(days=9)).isoformat()}]
    due = followups(apps, today=now)
    assert due[0]['overdue'] and due[0]['days_overdue'] == 2


def test_application_inside_the_cadence_is_not_overdue():
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    apps = [{'id': 'a', 'status': 'SUBMITTED', 'updated_at': (now - timedelta(days=2)).isoformat()}]
    assert followups(apps, today=now)[0]['overdue'] is False


def test_followup_cap_retires_an_application():
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    apps = [{'id': 'a', 'status': 'SUBMITTED', 'followups_sent': 2,
             'updated_at': (now - timedelta(days=60)).isoformat()}]
    assert followups(apps, today=now) == []


def test_terminal_states_are_not_chased():
    apps = [{'id': 'a', 'status': 'REJECTED', 'updated_at': '2026-01-01T00:00:00+00:00'}]
    assert followups(apps) == []


# ---------------------------------------------------------- channel rates
def test_advance_rate_per_channel():
    rows = [{'ats': 'greenhouse', 'status': 'SUBMITTED'},
            {'ats': 'greenhouse', 'status': 'INTERVIEW'},
            {'ats': 'lever', 'status': 'SUBMITTED'}]
    by = {r['channel']: r for r in channel_rates(rows)}
    assert by['greenhouse']['advance_rate'] == 50.0
    assert by['lever']['advance_rate'] == 0.0


# ------------------------------------------------------------- providers
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload if not isinstance(self._payload, (str, bytes)) else json.loads(self._payload)

    @property
    def content(self):
        return self._payload if isinstance(self._payload, bytes) else str(self._payload).encode()

    @property
    def text(self):
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)


def _stub(monkeypatch_payloads):
    """Serve captured payloads in order, so paginating adapters are exercised."""
    queue = list(monkeypatch_payloads)

    def fake_get(url, timeout=None, headers=None):
        return _FakeResponse(queue.pop(0) if len(queue) > 1 else queue[0])
    return fake_get


def _with_stub(payloads, fn, *args, **kwargs):
    original = P._get
    P._get = _stub(payloads)
    try:
        return fn(*args, **kwargs)
    finally:
        P._get = original


def test_greenhouse_parser():
    payload = {'jobs': [{'title': 'Backend Engineer', 'absolute_url': 'https://gh/1',
                         'location': {'name': 'Remote'},
                         'content': '<p>Build <b>things</b></p>', 'updated_at': '2026-05-01'}]}
    jobs = _with_stub([payload], P.greenhouse, 'Acme', slug='acme')
    assert jobs[0]['title'] == 'Backend Engineer'
    assert jobs[0]['location'] == 'Remote'
    # Block structure is preserved as newlines rather than flattened to spaces.
    assert jobs[0]['description'].split() == ['Build', 'things']


def test_lever_parser_merges_description_lists():
    payload = [{'text': 'SRE', 'hostedUrl': 'https://lever/1',
                'categories': {'location': 'Berlin'}, 'descriptionPlain': 'Run systems',
                'lists': [{'content': '<li>On-call</li>'}], 'createdAt': 1700000000}]
    jobs = _with_stub([payload], P.lever, 'Acme', slug='acme')
    assert 'Run systems' in jobs[0]['description'] and 'On-call' in jobs[0]['description']


def test_ashby_parser_marks_remote():
    payload = {'jobs': [{'title': 'PM', 'jobUrl': 'https://ashby/1', 'location': 'NYC',
                         'isRemote': True, 'descriptionPlain': 'Own the roadmap'}]}
    jobs = _with_stub([payload], P.ashby, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'NYC, Remote'


def test_workable_parser_builds_location_and_link():
    payload = {'name': 'Acme', 'jobs': [{'title': 'Designer', 'shortcode': 'ABC',
                                         'city': 'Lisbon', 'country': 'Portugal',
                                         'telecommuting': True, 'description': '<p>Design</p>',
                                         'published_on': '2026-04-02'}]}
    jobs = _with_stub([payload], P.workable, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'Lisbon, Portugal, Remote'
    assert jobs[0]['url'].endswith('/j/ABC')


def test_recruitee_parser():
    payload = {'offers': [{'title': 'QA', 'careers_url': 'https://r/1', 'city': 'Oslo',
                           'country': 'Norway', 'description': '<p>Test</p>'}]}
    jobs = _with_stub([payload], P.recruitee, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'Oslo, Norway' and jobs[0]['description'] == 'Test'


def test_pinpoint_parser_prefers_display_location():
    payload = {'data': [{'title': 'Analyst', 'url': 'https://p/1',
                         'location': {'name': 'London, UK'}, 'description': '<p>Analyse</p>'}]}
    jobs = _with_stub([payload], P.pinpoint, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'London, UK'


def test_breezy_parser_assembles_location():
    payload = [{'name': 'Chef', 'url': 'https://b/1',
                'location': {'city': 'Paris', 'country': {'name': 'France'}, 'is_remote': True},
                'description': '<p>Cook</p>'}]
    jobs = _with_stub([payload], P.breezy, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'Paris, France, Remote'


def test_rippling_parser():
    payload = [{'name': 'Recruiter', 'url': 'https://ri/1',
                'workLocation': {'label': 'Remote (US)'}, 'descriptionHtml': '<p>Hire</p>'}]
    jobs = _with_stub([payload], P.rippling, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'Remote (US)' and jobs[0]['description'] == 'Hire'


def test_personio_xml_parser():
    xml = b"""<?xml version="1.0"?><workzag-jobs><position>
      <name>Data Scientist</name><url>https://p.de/1</url><office>Munich</office>
      <department>Data</department>
      <jobDescriptions><jobDescription><name>Tasks</name>
      <value>&lt;p&gt;Model things&lt;/p&gt;</value></jobDescription></jobDescriptions>
    </position></workzag-jobs>"""
    jobs = _with_stub([xml], P.personio, 'Acme', slug='acme')
    assert jobs[0]['title'] == 'Data Scientist'
    assert jobs[0]['location'] == 'Munich, Data'
    assert 'Model things' in jobs[0]['description']


def test_smartrecruiters_paginates_and_fetches_details():
    page = {'content': [{'id': 'x1', 'name': 'Sales Lead',
                         'location': {'city': 'Madrid', 'country': 'es', 'remote': False}}],
            'totalFound': 1}
    detail = {'jobAd': {'sections': {'jobDescription': {'text': '<p>Sell</p>'}}}}
    jobs = _with_stub([page, detail], P.smartrecruiters, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'Madrid, es'
    assert jobs[0]['description'] == 'Sell'
    assert '_id' not in jobs[0]


def _with_post_stub(payloads, fn, *args, **kwargs):
    """Stub the POST helper for providers that paginate with a request body."""
    queue = list(payloads)
    original = P._post
    P._post = lambda url, payload, timeout=None, headers=None: _FakeResponse(
        queue.pop(0) if len(queue) > 1 else queue[0])
    try:
        return fn(*args, **kwargs)
    finally:
        P._post = original


def test_workday_derives_tenant_and_site_from_the_url():
    page = {'jobPostings': [{'title': 'Staff Engineer', 'externalPath': '/job/Berlin/Staff_R-1',
                             'locationsText': 'Berlin', 'postedOn': 'Posted Today'}]}
    jobs = _with_post_stub([page], P.workday, 'Acme',
                           url='https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers')
    assert jobs[0]['url'] == 'https://acme.wd5.myworkdayjobs.com/AcmeCareers/job/Berlin/Staff_R-1'
    assert jobs[0]['location'] == 'Berlin'


def test_workday_rejects_a_non_workday_url():
    try:
        P.workday('Acme', url='https://example.com/careers')
    except P.ProviderError:
        return
    raise AssertionError('expected a ProviderError')


def test_bamboohr_parser():
    payload = {'result': [{'id': 12, 'jobOpeningName': 'Recruiter',
                           'location': {'city': 'Austin', 'state': 'TX'}, 'isRemote': True}]}
    jobs = _with_stub([payload], P.bamboohr, 'Acme', slug='acme')
    assert jobs[0]['url'] == 'https://acme.bamboohr.com/careers/12'
    assert jobs[0]['location'] == 'Austin, TX, Remote'


def test_oraclecloud_flattens_requisition_list():
    payload = {'items': [{'requisitionList': [
        {'Title': 'Consultant', 'Id': 'REQ1', 'PrimaryLocation': 'Madrid',
         'PostedDate': '2026-05-01'}]}]}
    jobs = _with_stub([payload], P.oraclecloud, 'Acme',
                      url='https://acme.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1')
    assert jobs[0]['title'] == 'Consultant' and 'CX_1' in jobs[0]['url']


def test_eightfold_parser():
    payload = {'positions': [{'name': 'ML Engineer', 'canonicalPositionUrl': 'https://ef/1',
                              'location': 'Remote', 'job_description': '<p>Train</p>',
                              't_create': 1700000000}]}
    jobs = _with_stub([payload], P.eightfold, 'Acme', url='https://acme.eightfold.ai/careers')
    assert jobs[0]['description'] == 'Train'


def test_comeet_requires_uid_and_token():
    try:
        P.comeet('Acme', slug='justuid')
    except P.ProviderError:
        pass
    else:
        raise AssertionError('expected a ProviderError')
    payload = [{'name': 'Ops Lead', 'url_active_page': 'https://c/1',
                'location': {'city': 'Tel Aviv', 'country': 'IL'}}]
    jobs = _with_stub([payload], P.comeet, 'Acme', slug='uid123/tok456')
    assert jobs[0]['location'] == 'Tel Aviv, IL'


def test_getro_reads_nested_results():
    payload = {'results': {'jobs': [{'title': 'Founding Engineer', 'url': 'https://g/1',
                                     'organization': {'name': 'Startup'},
                                     'locations': ['Remote', 'EU']}]}}
    jobs = _with_post_stub([payload], P.getro, 'Network', slug='42')
    assert jobs[0]['company'] == 'Startup' and jobs[0]['location'] == 'Remote, EU'


def test_softgarden_parser():
    payload = {'jobs': [{'jobTitle': 'Controller', 'jobDetailUrl': 'https://sg/1',
                         'location': {'city': 'Hamburg'}, 'jobDescription': '<p>Count</p>'}]}
    jobs = _with_stub([payload], P.softgarden, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'Hamburg' and jobs[0]['description'] == 'Count'


def test_jobvite_parser():
    payload = {'jobs': [{'title': 'Account Exec', 'eId': 'oX1', 'location': 'Chicago'}]}
    jobs = _with_stub([payload], P.jobvite, 'Acme', slug='acme')
    assert jobs[0]['url'].endswith('/acme/job/oX1')


def test_join_parser_marks_remote():
    payload = {'jobs': [{'title': 'Growth Lead', 'idParam': 'g1',
                         'location': {'city': 'Berlin'}, 'remote': True}]}
    jobs = _with_stub([payload], P.join, 'Acme', slug='acme')
    assert jobs[0]['location'] == 'Berlin, Remote'
    assert jobs[0]['url'] == 'https://join.com/companies/acme/jobs/g1'


def test_url_based_providers_are_declared():
    # These have no meaningful slug, so watchlist validation must not demand one.
    assert P.URL_BASED == {'workday', 'oraclecloud', 'eightfold'}
    for pid in P.URL_BASED:
        assert pid in P.PROVIDERS


def test_every_provider_has_slug_help():
    for pid in P.PROVIDERS:
        assert P.SLUG_HELP.get(pid), pid


def test_detect_maps_every_supported_host():
    cases = [
        ('https://boards.greenhouse.io/anthropic', 'greenhouse', 'anthropic'),
        ('https://job-boards.greenhouse.io/stripe/jobs/1', 'greenhouse', 'stripe'),
        ('https://boards.greenhouse.io/embed/job_board?for=acme', 'greenhouse', 'acme'),
        ('https://jobs.lever.co/netflix', 'lever', 'netflix'),
        ('https://jobs.ashbyhq.com/openai', 'ashby', 'openai'),
        ('https://apply.workable.com/foo/', 'workable', 'foo'),
        ('https://acme.recruitee.com/', 'recruitee', 'acme'),
        ('https://acme.jobs.personio.de/', 'personio', 'acme'),
        ('https://acme.teamtailor.com/jobs', 'teamtailor', 'acme'),
        ('https://acme.pinpointhq.com', 'pinpoint', 'acme'),
        ('https://acme.breezy.hr/p/1-eng', 'breezy', 'acme'),
        ('https://ats.rippling.com/acme/jobs', 'rippling', 'acme'),
        ('https://acme.bamboohr.com/careers', 'bamboohr', 'acme'),
        ('https://acme.softgarden.io/en/jobs', 'softgarden', 'acme'),
        ('https://jobs.jobvite.com/acme', 'jobvite', 'acme'),
        ('https://join.com/companies/acme/jobs/1', 'join', 'acme'),
        # URL-addressed boards resolve the provider but deliberately no slug.
        ('https://acme.wd5.myworkdayjobs.com/en-US/Careers', 'workday', ''),
        ('https://acme.eightfold.ai/careers', 'eightfold', ''),
        ('https://www.comeet.co/careers-api/2.0/company/uid1/positions?token=tok1',
         'comeet', 'uid1/tok1'),
        ('https://example.com/careers', None, ''),
    ]
    for url, provider, slug in cases:
        assert P.detect(url) == (provider, slug), url


def test_slug_injection_is_rejected():
    for bad in ('../../etc', 'a/b', 'a?b', ''):
        try:
            P._slug(bad)
        except P.ProviderError:
            continue
        raise AssertionError(f'slug {bad!r} should have been rejected')


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
