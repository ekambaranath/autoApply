"""Canonical application states, their aliases, and lifecycle ordering.

Adapted from career-ops (MIT, (c) 2026 Santiago Fernandez de Valderrama) —
`templates/states.yml`. https://github.com/santifer/career-ops

One roster in one place. When several consumers each keep their own status map
they drift, and a row normalizes three different ways — silently vanishing from
whichever funnel does not recognise its spelling.
"""

#: id -> (label, aliases, terminal). Order is the lifecycle order; a state
#: marked terminal has no ordering among the other terminal states, but still
#: supersedes every non-terminal one.
STATES = [
    ('DISCOVERED',       'Discovered',       ('new',),                                  False),
    ('READY_FOR_REVIEW', 'Ready for review', ('prepared', 'evaluated', 'draft'),        False),
    ('APPROVED',         'Approved',         ('ready_to_submit',),                      False),
    ('SUBMITTED',        'Submitted',        ('applied', 'sent'),                       False),
    ('RESPONDED',        'Responded',        ('replied',),                              False),
    ('INTERVIEW',        'Interview',        ('interviewing', 'onsite', 'screen'),      False),
    ('OFFER',            'Offer',            ('offered',),                              True),
    ('HIRED',            'Hired',            ('accepted',),                             True),
    ('REJECTED',         'Rejected',         ('declined_by_company',),                  True),
    ('WITHDRAWN',        'Withdrawn',        ('discarded', 'closed', 'cancelled'),      True),
    ('SKIPPED',          'Skipped',          ('skip', 'not_a_fit', 'monitor'),          True),
    # Agent-run outcomes. These are states of the automation, not of the
    # conversation with the employer, so they sit outside the lifecycle order.
    ('SECURITY_CHALLENGE', 'Security challenge', ('captcha', 'mfa'),                    False),
    ('ERROR',            'Error',            ('failed',),                               False),
]

LABELS = {sid: label for sid, label, _a, _t in STATES}
TERMINAL = {sid for sid, _l, _a, terminal in STATES if terminal}
ORDER = {sid: i for i, (sid, _l, _a, _t) in enumerate(STATES)}

#: Reaching one of these means the employer engaged — the number that matters
#: when judging whether applications are landing.
ADVANCED = {'RESPONDED', 'INTERVIEW', 'OFFER', 'HIRED'}

#: States where the application is still live and worth chasing.
ACTIONABLE = {'SUBMITTED', 'RESPONDED', 'INTERVIEW'}

_ALIASES = {}
for _sid, _label, _aliases, _terminal in STATES:
    _ALIASES[_sid.lower()] = _sid
    _ALIASES[_label.lower()] = _sid
    for _a in _aliases:
        _ALIASES[_a.lower()] = _sid


def fold(status):
    """Normalize any spelling or alias to a canonical state id.

    Unrecognised input is returned upper-cased rather than dropped, so a new
    state shows up in the UI as itself instead of disappearing.
    """
    key = str(status or '').strip().lower().replace(' ', '_')
    return _ALIASES.get(key) or str(status or '').strip().upper()


def label(status):
    return LABELS.get(fold(status), str(status or '').replace('_', ' ').title())


def is_terminal(status):
    return fold(status) in TERMINAL


def compare_lifecycle(a, b):
    """Negative when `a` is earlier in the lifecycle than `b`, 0 when equal.

    Used to refuse a status update that would move an application backwards.
    """
    fa, fb = fold(a), fold(b)
    if fa == fb:
        return 0
    ta, tb = fa in TERMINAL, fb in TERMINAL
    if ta and tb:
        return 0
    if ta != tb:
        return 1 if ta else -1
    return (ORDER.get(fa, 99) > ORDER.get(fb, 99)) - (ORDER.get(fa, 99) < ORDER.get(fb, 99))
