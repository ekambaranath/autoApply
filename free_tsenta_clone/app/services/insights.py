"""Pipeline insights: reposts, posting legitimacy, follow-up cadence, channel rates.

The repost clustering and the follow-up cadence model are adapted from
career-ops (MIT, (c) 2026 Santiago Fernandez de Valderrama) — `detect-reposts.mjs`,
`followup-cadence.mjs` and `analyze-patterns.mjs`.
https://github.com/santifer/career-ops

The legitimacy signals below are inspired by that project's "Block G" posting
check, which is deliberately kept separate from the match score: whether a
posting looks real is a different question from whether it suits you, and
folding one into the other hides both.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .role_match import title_identity_key
from .states import fold, ADVANCED, ACTIONABLE

REPOST_WINDOW_DAYS = 90
# Two URLs first seen on the SAME day were listed side by side in one sweep —
# that is a company running two requisitions at once, the opposite of
# re-listing one later, and it is the largest single source of false positives.
MIN_REPOST_SPAN_DAYS = 1


def _parse(dt):
    if not dt:
        return None
    text = str(dt).strip().replace('Z', '+00:00')
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        try:
            d = datetime.strptime(text[:10], '%Y-%m-%d')
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _days(a, b):
    return abs((b - a).days)


# ------------------------------------------------------------- reposts
def detect_reposts(jobs, window_days=REPOST_WINDOW_DAYS, min_span_days=MIN_REPOST_SPAN_DAYS):
    """Group a company's postings that look like re-listings of one requisition.

    A cluster counts only when it holds two or more *distinct URLs* (the same
    URL seen twice is a dedup hit, not a repost), every sighting falls inside
    `window_days` of the others, and the span between first and last is at
    least `min_span_days`.

    Membership is decided by an equality key rather than pairwise similarity:
    a large employer accumulates thousands of distinct titles, so comparing
    every pair is quadratic — and pairwise similarity also merged genuine
    sibling requisitions, which is the correctness reason for the key.
    """
    by_company = defaultdict(list)
    for j in jobs:
        seen = _parse(j.get('posted_at') or j.get('created_at'))
        if not seen or not j.get('url'):
            continue
        by_company[(j.get('company') or '').strip().lower()].append({**j, '_seen': seen})

    clusters = []
    for company, rows in by_company.items():
        if len(rows) < 2:
            continue
        groups = defaultdict(list)
        for r in rows:
            groups[title_identity_key(r.get('title'))].append(r)
        for group in groups.values():
            if len(group) < 2:
                continue
            # Collapse repeat sightings of one URL to its earliest, so a URL
            # seen on several scans cannot inflate the repost count.
            by_url = {}
            for r in sorted(group, key=lambda x: x['_seen']):
                by_url.setdefault(r['url'], r)
            deduped = sorted(by_url.values(), key=lambda x: x['_seen'])
            if len(deduped) < 2:
                continue
            span = _days(deduped[0]['_seen'], deduped[-1]['_seen'])
            if span > window_days or span < min_span_days:
                continue
            clusters.append({
                'company': deduped[-1].get('company') or company,
                'role': deduped[-1].get('title'),
                'repost_count': len(deduped),
                'first_seen': deduped[0]['_seen'].date().isoformat(),
                'last_seen': deduped[-1]['_seen'].date().isoformat(),
                'days_span': span,
                'appearances': [{'url': r['url'], 'date': r['_seen'].date().isoformat(),
                                 'title': r.get('title'), 'job_id': r.get('id')} for r in deduped],
            })
    clusters.sort(key=lambda c: (-c['repost_count'], c['company']))
    return clusters


# -------------------------------------------------------- legitimacy
_SALARY_RE = re.compile(
    r'(\$|€|£|₹)\s?\d|\b\d{2,3}[,.]?\d{3}\s?(-|–|to)\s?\d{2,3}[,.]?\d{3}'
    r'|\b(salary|compensation|base pay|pay range|comp range)\b', re.I)
_UPFRONT_RE = re.compile(
    r'\b(training fee|registration fee|pay .{0,20}(upfront|in advance)|security deposit'
    r'|purchase .{0,20}(equipment|starter kit)|processing fee)\b', re.I)
_OFF_CHANNEL_RE = re.compile(
    r'\b(telegram|whatsapp|signal app|text me at|contact me on)\b', re.I)
_HYPE_RE = re.compile(
    r'\b(unlimited earning|earn up to \$?\d|no experience (necessary|required)'
    r'|work from home and earn|immediate start|urgent(ly)? hiring|be your own boss)\b', re.I)
_GHOST_RE = re.compile(
    r'\b(always (accepting|hiring)|evergreen (req|role|posting)|general application'
    r'|talent (pool|community|network)|future opportunities|speculative application)\b', re.I)

#: The minimum body length below which a posting says too little to evaluate.
_THIN_DESCRIPTION_CHARS = 400


def legitimacy_signals(job, repost_count=0, age_days=None):
    """Flag things worth a second look before spending effort on a posting.

    These are *signals*, never verdicts: a real posting can trip one, and a
    fake one can trip none. They are kept out of the match score on purpose —
    "is this posting real" and "does this job suit me" are different questions,
    and averaging them hides both.

    Returns ``{'flags': [...], 'level': 'clear'|'notice'|'caution'}``.
    """
    desc = job.get('description') or ''
    flags = []

    if _UPFRONT_RE.search(desc):
        flags.append({'code': 'asks_for_money', 'severity': 'critical',
                      'text': 'Mentions an upfront fee or purchase — legitimate employers never charge to hire.'})
    if _OFF_CHANNEL_RE.search(desc):
        flags.append({'code': 'off_channel_contact', 'severity': 'critical',
                      'text': 'Directs applicants to a personal messaging app rather than a company channel.'})
    if _HYPE_RE.search(desc):
        flags.append({'code': 'unrealistic_pitch', 'severity': 'serious',
                      'text': 'Uses earnings or urgency language typical of low-quality listings.'})
    if _GHOST_RE.search(desc):
        flags.append({'code': 'evergreen_posting', 'severity': 'warning',
                      'text': 'Reads as a talent-pool or evergreen posting rather than a specific opening.'})
    if repost_count >= 3:
        flags.append({'code': 'frequently_reposted', 'severity': 'warning',
                      'text': f'Re-listed {repost_count} times — may be a ghost job or a hard-to-fill req.'})
    if age_days is not None and age_days > 90:
        flags.append({'code': 'stale_posting', 'severity': 'warning',
                      'text': f'First seen {age_days} days ago and still listed.'})
    if len(desc.strip()) < _THIN_DESCRIPTION_CHARS:
        flags.append({'code': 'thin_description', 'severity': 'notice',
                      'text': 'Very short description — not enough detail to judge the role.'})
    if not (job.get('company') or '').strip():
        flags.append({'code': 'no_company', 'severity': 'notice',
                      'text': 'No company named on the posting.'})
    if not _SALARY_RE.search(desc):
        flags.append({'code': 'no_salary', 'severity': 'notice',
                      'text': 'No compensation stated.'})

    worst = {'critical': 3, 'serious': 3, 'warning': 2, 'notice': 1}
    level = max((worst[f['severity']] for f in flags), default=0)
    return {'flags': flags, 'level': {0: 'clear', 1: 'notice', 2: 'caution', 3: 'caution'}[level]}


# ----------------------------------------------------- follow-up cadence
DEFAULT_CADENCE = {
    'applied_first': 7,        # days after submitting before the first nudge
    'applied_subsequent': 7,   # days between later nudges
    'applied_max_followups': 2,
    'responded_initial': 1,
    'responded_subsequent': 3,
    'interview_thankyou': 1,
}


def followups(applications, cadence=None, today=None):
    """Work out which live applications are due a follow-up, and which are overdue.

    `applications` are dicts with at least ``id``, ``status`` and
    ``updated_at``; ``followups_sent`` is honoured when present.
    """
    cad = {**DEFAULT_CADENCE, **(cadence or {})}
    now = today or datetime.now(timezone.utc)
    out = []
    for a in applications:
        state = fold(a.get('status'))
        if state not in ACTIONABLE:
            continue
        anchor = _parse(a.get('followed_up_at') or a.get('updated_at') or a.get('created_at'))
        if not anchor:
            continue
        sent = int(a.get('followups_sent') or 0)

        if state == 'SUBMITTED':
            if sent >= cad['applied_max_followups']:
                continue
            wait = cad['applied_first'] if sent == 0 else cad['applied_subsequent']
            reason = 'No reply since applying'
        elif state == 'RESPONDED':
            wait = cad['responded_initial'] if sent == 0 else cad['responded_subsequent']
            reason = 'Keep the conversation moving'
        else:  # INTERVIEW
            wait = cad['interview_thankyou']
            reason = 'Send a thank-you note'

        due = anchor + timedelta(days=wait)
        days_over = (now - due).days
        out.append({
            'application_id': a.get('id'),
            'title': a.get('title'), 'company': a.get('company'),
            'status': state,
            'due_date': due.date().isoformat(),
            'days_until_due': -days_over if days_over < 0 else 0,
            'days_overdue': max(0, days_over),
            'overdue': days_over >= 0,
            'followups_sent': sent,
            'reason': reason,
        })
    out.sort(key=lambda x: (not x['overdue'], -x['days_overdue'], x['due_date']))
    return out


# --------------------------------------------------------- channel rates
def channel_rates(rows, key='ats', min_volume=1):
    """Advance rate per channel: of the applications sent through each ATS,
    how many drew any employer engagement.

    A channel with one application has no meaningful rate, so `min_volume`
    lets the caller keep the long tail out of a chart.
    """
    sent = Counter()
    advanced = Counter()
    for r in rows:
        channel = (r.get(key) or 'unknown').lower()
        state = fold(r.get('status'))
        if state in ('SUBMITTED',) or state in ADVANCED:
            sent[channel] += 1
        if state in ADVANCED:
            advanced[channel] += 1
    out = []
    for channel, n in sent.most_common():
        if n < min_volume:
            continue
        out.append({'channel': channel, 'applications': n, 'advanced': advanced[channel],
                    'advance_rate': round(advanced[channel] / n * 100, 1)})
    return out


def rejection_patterns(applications):
    """Where applications stop, so the weakest stage is visible."""
    counts = Counter(fold(a.get('status')) for a in applications)
    total = sum(counts.values()) or 1
    return [{'status': s, 'count': n, 'share': round(n / total * 100, 1)}
            for s, n in counts.most_common()]
