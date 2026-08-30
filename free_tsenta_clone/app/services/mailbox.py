"""Close the tracking loop: read employer replies over IMAP and classify them.

Statuses otherwise only move when you remember to log them by hand, which is
exactly the step that gets skipped. This reads the inbox, matches each message
to an application, decides what it means, and advances the status.

Classification is deliberately conservative:

* Rejections are matched before interviews, because a rejection often mentions
  the interview it is declining to schedule ("we won't be moving forward to
  interview"), and reading that as an invitation is the costliest error here.
* An application never moves backwards, and never leaves a terminal state.
* Anything it cannot place is stored as `UNMATCHED` for you to look at, rather
  than guessed at.

Credentials come from the environment and are never written to the database:

    MAIL_IMAP_HOST=imap.gmail.com      # Gmail, Outlook and Fastmail all work
    MAIL_IMAP_PORT=993
    MAIL_USER=you@example.com
    MAIL_PASSWORD=<app password>       # NOT your account password
    MAIL_FOLDER=INBOX

Gmail and Outlook require an app-specific password with 2FA enabled; a normal
password is rejected by the provider.
"""
import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

from .core import audit, db, get_setting, now, set_setting
from .role_match import normalize_title
from .states import ACTIONABLE, TERMINAL, fold

# Ordered: the first pattern that matches wins, so the risky readings are last.
RULES = [
    ('REJECTED', re.compile(
        r'\b(unfortunately|regret to inform|not (be )?(moving|proceeding) forward'
        r'|will not be (moving|progressing)|decided (not to|to move forward with other)'
        r'|other candidates|unsuccessful on this occasion|no longer under consideration'
        r'|position has been filled|pursue other candidates)\b', re.I)),
    ('OFFER', re.compile(
        r'\b(offer of employment|pleased to offer|formal offer|offer letter'
        r'|extend an offer|we would like to offer)\b', re.I)),
    ('INTERVIEW', re.compile(
        r'\b(schedule (a|an|your) (call|interview|chat)|invite you to interview'
        r'|would like to (set up|arrange|schedule)|book a time|availability for a'
        r'|technical (interview|screen)|phone screen|next round|meet the team'
        r'|interview invitation|calendly\.com|schedule your)\b', re.I)),
    ('RESPONDED', re.compile(
        r'\b(thank you for (your )?(applying|application|interest)|we received your application'
        r'|application (has been )?received|reviewing your application'
        r'|your application (for|to)|acknowledg)\b', re.I)),
]

# Bulk senders that are never a human recruiter replying about one application.
NOISE = re.compile(r'\b(no-?reply|do-?not-?reply|newsletter|notifications?@|digest'
                   r'|jobalert|job-alerts|marketing@)\b', re.I)


def configured():
    return bool(os.getenv('MAIL_IMAP_HOST') and os.getenv('MAIL_USER') and os.getenv('MAIL_PASSWORD'))


def config():
    return {'host': os.getenv('MAIL_IMAP_HOST', ''), 'port': int(os.getenv('MAIL_IMAP_PORT', '993')),
            'user': os.getenv('MAIL_USER', ''), 'folder': os.getenv('MAIL_FOLDER', 'INBOX'),
            'configured': configured()}


def _decode(value):
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _body(msg):
    """Plain-text body, preferring text/plain and skipping attachments."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() != 'text/plain':
                continue
            if 'attachment' in str(part.get('Content-Disposition') or ''):
                continue
            try:
                parts.append(part.get_payload(decode=True).decode(
                    part.get_content_charset() or 'utf-8', 'ignore'))
            except Exception:
                continue
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode(
                msg.get_content_charset() or 'utf-8', 'ignore'))
        except Exception:
            pass
    return '\n'.join(parts)[:20000]


def classify(subject, body):
    """Decide what a message means. Returns a state id, or None."""
    text = f'{subject}\n{body}'
    for state, pattern in RULES:
        if pattern.search(text):
            return state
    return None


def _whole_word(needle, haystack):
    """Substring match anchored to word boundaries on both sides."""
    return bool(re.search(rf'(?<!\w){re.escape(needle)}(?!\w)', haystack))


def _candidates():
    """Live applications, with the tokens used to match a message to them."""
    c = db()
    rows = [dict(r) for r in c.execute(
        'SELECT a.id,a.status,a.created_at,j.title,j.company,j.url '
        'FROM applications a JOIN jobs j ON j.id=a.job_id')]
    c.close()
    out = []
    for r in rows:
        if fold(r['status']) in TERMINAL:
            continue
        company = (r.get('company') or '').strip()
        out.append({**r,
                    'company_key': normalize_title(company),
                    # "Acme Inc." in the tracker vs "acme.com" in the sender domain.
                    'company_word': re.sub(r'[^a-z0-9]', '', normalize_title(company).split(' ')[0])
                    if company else '',
                    'title_key': normalize_title(r.get('title') or '')})
    return out


def match_application(subject, body, sender, apps):
    """Find the application a message is about.

    Company name in the sender domain is the strongest signal, then company in
    the text, then a distinctive role title. Ambiguity is resolved toward the
    most recent application, since a fresh thread is far likelier than an old one.
    """
    haystack = normalize_title(f'{subject} {body[:2000]} {sender}')
    domain = (sender.split('@')[-1].rstrip('>').lower() if '@' in sender else '')
    scored = []
    for a in apps:
        score = 0
        if a['company_word'] and len(a['company_word']) > 3 and a['company_word'] in domain:
            score += 5
        # Whole-word, not substring: a two-letter company like "Ai" otherwise
        # matches inside "mailchimp" and claims every unrelated message.
        if a['company_key'] and _whole_word(a['company_key'], haystack):
            score += 3
        if a['title_key'] and len(a['title_key']) > 8 and _whole_word(a['title_key'], haystack):
            score += 3
        if a['url'] and a['url'] in body:
            score += 4
        if score:
            scored.append((score, a['created_at'] or '', a))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return scored[0][2]


def _advance(app_id, current, new_state, subject, sender):
    """Move an application forward, never backwards and never out of a terminal state."""
    from .states import ORDER
    cur = fold(current)
    if cur in TERMINAL:
        return False
    if ORDER.get(new_state, 99) <= ORDER.get(cur, -1) and new_state not in TERMINAL:
        return False
    c = db()
    c.execute('UPDATE applications SET status=?,updated_at=? WHERE id=?', (new_state, now(), app_id))
    c.commit(); c.close()
    audit(app_id, new_state, {'source': 'email', 'subject': subject[:200], 'from': sender[:200]})
    return True


def sync(limit=100, days=30, dry_run=False):
    """Read recent mail, classify it, and advance matching applications."""
    if not configured():
        raise RuntimeError('Mailbox is not configured — set MAIL_IMAP_HOST, MAIL_USER '
                           'and MAIL_PASSWORD (an app password, not your login password)')
    cfg = config()
    seen = set(filter(None, (get_setting('mail_seen_uids', '') or '').split(',')))
    apps = _candidates()
    results = []

    conn = imaplib.IMAP4_SSL(cfg['host'], cfg['port'])
    try:
        conn.login(cfg['user'], os.getenv('MAIL_PASSWORD'))
        conn.select(cfg['folder'], readonly=True)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%d-%b-%Y')
        status, data = conn.search(None, f'(SINCE {since})')
        if status != 'OK':
            raise RuntimeError(f'IMAP search failed: {status}')
        uids = data[0].split()[-limit:]
        for uid in uids:
            key = uid.decode()
            if key in seen:
                continue
            status, payload = conn.fetch(uid, '(RFC822)')
            if status != 'OK' or not payload or not payload[0]:
                continue
            msg = email.message_from_bytes(payload[0][1])
            sender = _decode(msg.get('From'))
            subject = _decode(msg.get('Subject'))
            if NOISE.search(sender):
                seen.add(key)
                continue
            body = _body(msg)
            state = classify(subject, body)
            app = match_application(subject, body, sender, apps) if state else None
            entry = {'uid': key, 'from': sender, 'subject': subject, 'date': _decode(msg.get('Date')),
                     'classified': state or 'UNCLEAR',
                     'application_id': app['id'] if app else None,
                     'company': app['company'] if app else None,
                     'title': app['title'] if app else None,
                     'applied': False}
            if state and app and not dry_run:
                entry['applied'] = _advance(app['id'], app['status'], state, subject, sender)
                if entry['applied']:
                    app['status'] = state
            if not app:
                entry['classified'] = state or 'UNCLEAR'
                entry['reason'] = 'No matching application' if state else 'No rule matched'
            results.append(entry)
            seen.add(key)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    if not dry_run:
        # Cap the marker list so it cannot grow without bound.
        set_setting('mail_seen_uids', ','.join(list(seen)[-2000:]))
        set_setting('mail_last_sync', now())
    return {'checked': len(results), 'updated': sum(1 for r in results if r['applied']),
            'messages': results}


def last_sync():
    return get_setting('mail_last_sync', None)
