"""Tests for employer-reply classification and application matching.

No IMAP connection is involved: classify() and match_application() are pure
functions over a subject, a body and a sender.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.mailbox import NOISE, classify, match_application
from app.services.role_match import normalize_title


def _app(aid, company, title, status='SUBMITTED', created='2026-05-01', url=''):
    import re
    key = normalize_title(company)
    return {'id': aid, 'company': company, 'title': title, 'status': status,
            'created_at': created, 'url': url, 'company_key': key,
            'company_word': re.sub(r'[^a-z0-9]', '', key.split(' ')[0]) if company else '',
            'title_key': normalize_title(title)}


# ---------------------------------------------------------- classification
def test_plain_rejection():
    assert classify('Your application', 'Unfortunately we will not be moving forward.') == 'REJECTED'


def test_rejection_wins_over_interview_wording():
    # The costliest error: a rejection that mentions the interview it declines.
    body = 'We regret to inform you that we are not moving forward to schedule an interview.'
    assert classify('Update on your application', body) == 'REJECTED'


def test_rejection_phrased_as_other_candidates():
    assert classify('Update', 'We decided to move forward with other candidates.') == 'REJECTED'


def test_interview_invitation():
    assert classify('Next steps', 'We would like to schedule a call with you.') == 'INTERVIEW'


def test_interview_via_scheduling_link():
    assert classify('Chat?', 'Grab a slot here: https://calendly.com/acme/30min') == 'INTERVIEW'


def test_offer_beats_interview():
    body = 'We are pleased to offer you the role. We can schedule a call to discuss.'
    assert classify('Great news', body) == 'OFFER'


def test_acknowledgement_is_only_a_response():
    assert classify('We received your application', 'Thank you for applying to Acme.') == 'RESPONDED'


def test_unrelated_mail_is_unclassified():
    assert classify('Lunch tomorrow?', 'Are you free at 1pm?') is None


def test_empty_message_is_unclassified():
    assert classify('', '') is None


def test_noise_senders_are_recognised():
    for sender in ('no-reply@acme.com', 'donotreply@x.io', 'notifications@y.com',
                   'jobalert@indeed.com', 'newsletter@z.dev'):
        assert NOISE.search(sender), sender
    assert not NOISE.search('sarah.recruiter@acme.com')


# -------------------------------------------------------------- matching
APPS = [
    _app('a1', 'Acme Corp', 'Senior Python Engineer'),
    _app('a2', 'Globex', 'Data Engineer'),
    _app('a3', 'Initech', 'Site Reliability Engineer'),
]


def test_matches_on_sender_domain():
    got = match_application('Your application', 'Thanks for applying.',
                            'Sarah <sarah@acmecorp.com>', APPS)
    assert got and got['id'] == 'a1'


def test_matches_on_company_named_in_the_body():
    got = match_application('Update', 'Your application to Globex was reviewed.',
                            'noreply@mail.example', APPS)
    assert got and got['id'] == 'a2'


def test_matches_on_a_distinctive_role_title():
    got = match_application('Site Reliability Engineer', 'About the role you applied for.',
                            'someone@unknown.io', APPS)
    assert got and got['id'] == 'a3'


def test_matches_on_the_posting_url():
    apps = [_app('a9', 'Hooli', 'Engineer', url='https://boards.example.com/hooli/9')]
    got = match_application('Re: application', 'Ref https://boards.example.com/hooli/9 thanks',
                            'x@y.z', apps)
    assert got and got['id'] == 'a9'


def test_no_signal_means_no_match():
    assert match_application('Newsletter', 'Ten tips for developers.', 'a@b.c', APPS) is None


def test_terminal_applications_are_not_candidates():
    # _candidates() filters these out; matching should never resurrect one.
    from app.services.states import TERMINAL, fold
    assert fold('REJECTED') in TERMINAL and fold('HIRED') in TERMINAL


def test_ambiguity_prefers_the_most_recent_application():
    apps = [_app('old', 'Acme Corp', 'Engineer', created='2026-01-01'),
            _app('new', 'Acme Corp', 'Engineer', created='2026-06-01')]
    got = match_application('Hello', 'Regarding Acme Corp.', 'r@acmecorp.com', apps)
    assert got['id'] == 'new'


def test_short_company_names_do_not_match_any_domain():
    # A two-letter company must not match every sender domain containing it.
    apps = [_app('s1', 'Ai', 'Engineer')]
    assert match_application('Hi', 'Unrelated text.', 'someone@mailchimp.com', apps) is None


# ------------------------------------------------- end-to-end sync (stubbed IMAP)
def _message(sender, subject, body):
    return (f'From: {sender}\r\nSubject: {subject}\r\n'
            f'Date: Mon, 01 Jun 2026 10:00:00 +0000\r\n'
            f'Content-Type: text/plain; charset="utf-8"\r\n\r\n{body}').encode()


class _FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL covering the calls sync() makes."""
    inbox = []

    def __init__(self, host, port):
        self.host = host

    def login(self, user, password):
        return ('OK', [b'ok'])

    def select(self, folder, readonly=False):
        return ('OK', [b'1'])

    def search(self, charset, query):
        return ('OK', [b' '.join(str(i + 1).encode() for i in range(len(self.inbox)))])

    def fetch(self, uid, spec):
        return ('OK', [(b'', self.inbox[int(uid) - 1])])

    def logout(self):
        return ('BYE', [b'bye'])


def _sync_with(inbox, apps, **kwargs):
    """Run sync() against a fake mailbox and a fixed candidate list."""
    import os
    from app.services import mailbox as M
    _FakeIMAP.inbox = inbox
    saved = {k: os.environ.get(k) for k in
             ('MAIL_IMAP_HOST', 'MAIL_USER', 'MAIL_PASSWORD')}
    os.environ.update(MAIL_IMAP_HOST='imap.test', MAIL_USER='me@test', MAIL_PASSWORD='pw')
    orig_imap, orig_cands = M.imaplib.IMAP4_SSL, M._candidates
    orig_get, orig_set, orig_adv = M.get_setting, M.set_setting, M._advance
    moved = []
    M.imaplib.IMAP4_SSL = _FakeIMAP
    M._candidates = lambda: apps
    M.get_setting = lambda k, d=None: d
    M.set_setting = lambda k, v: None
    M._advance = lambda aid, cur, new, subj, sender: (moved.append((aid, new)), True)[1]
    try:
        return M.sync(**kwargs), moved
    finally:
        M.imaplib.IMAP4_SSL, M._candidates = orig_imap, orig_cands
        M.get_setting, M.set_setting, M._advance = orig_get, orig_set, orig_adv
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.update({k: v})


def test_sync_classifies_matches_and_advances():
    inbox = [_message('sarah@acmecorp.com', 'Your application',
                      'We would like to schedule a call with you next week.')]
    result, moved = _sync_with(inbox, [_app('a1', 'Acme Corp', 'Senior Python Engineer')])
    assert result['checked'] == 1 and result['updated'] == 1
    assert moved == [('a1', 'INTERVIEW')]
    assert result['messages'][0]['application_id'] == 'a1'


def test_sync_dry_run_changes_nothing():
    inbox = [_message('sarah@acmecorp.com', 'Update',
                      'Unfortunately we are not moving forward with your application.')]
    result, moved = _sync_with(inbox, [_app('a1', 'Acme Corp', 'Engineer')], dry_run=True)
    assert result['messages'][0]['classified'] == 'REJECTED'
    assert result['updated'] == 0 and moved == []


def test_sync_skips_bulk_senders():
    inbox = [_message('no-reply@jobalerts.com', 'New jobs for you',
                      'We would like to schedule a call about 20 new roles.')]
    result, moved = _sync_with(inbox, [_app('a1', 'Acme Corp', 'Engineer')])
    assert result['checked'] == 0 and moved == []


def test_sync_reports_unmatched_mail_without_guessing():
    inbox = [_message('someone@unrelated.io', 'Interview invite',
                      'We would like to schedule a call.')]
    result, moved = _sync_with(inbox, [_app('a1', 'Acme Corp', 'Engineer')])
    msg = result['messages'][0]
    assert moved == [] and msg['application_id'] is None
    assert msg['reason'] == 'No matching application'


def test_sync_requires_configuration():
    import os
    from app.services import mailbox as M
    saved = os.environ.pop('MAIL_IMAP_HOST', None)
    try:
        M.sync()
    except RuntimeError as e:
        assert 'not configured' in str(e)
    else:
        raise AssertionError('expected a RuntimeError')
    finally:
        if saved:
            os.environ['MAIL_IMAP_HOST'] = saved


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
