"""Title and content keyword filtering.

Adapted to Python from career-ops (MIT, (c) 2026 Santiago Fernandez de
Valderrama) — `title-keywords.mjs`. https://github.com/santifer/career-ops

A plain substring keyword is two loosenesses at once, and usually only one is
wanted: bare `agent` keeps Agentforce, Agentic *and* Reagents. The prefixes let
one entry ask for the reading it means:

    agent        substring — matches all three
    word:agent   exactly that word — rejects Agentforce
    stem:agent   a word starting with it — keeps Agentforce, drops Reagents

Two-to-three-letter all-letter acronyms are anchored automatically, so "COO"
never matches inside "Coordinator".
"""
import re

WORD_PREFIX = 'word:'
STEM_PREFIX = 'stem:'

# " + " between terms means every term must appear, in any order. The
# surrounding whitespace is load-bearing: a bare split on "+" would turn the
# ordinary keyword "C++" into "c", which matches almost every title — trading a
# silent drop for a silent flood.
AND_SEPARATOR = re.compile(r'\s+\+\s+')

# One definition of "inside a word", used by every branch below. An ASCII-only
# boundary treats an accented letter as a separator, so `word:intern` would
# match inside an accented "preintern" and veto exactly the international
# titles the prefix exists to protect. \w with re.UNICODE covers letters,
# digits and underscore; combining marks are added so a decomposed "e" plus
# accent does not split a word either.
_WORD_CHAR = r'[^\W]|[̀-ͯ]'


def _anchored(body):
    """Boundaries on both sides: the keyword is the whole word."""
    return re.compile(rf'(?<!{_WORD_CHAR}){body}(?!{_WORD_CHAR})', re.UNICODE)


def _stem(body):
    """Left boundary only: the keyword starts a word that may continue."""
    return re.compile(rf'(?<!{_WORD_CHAR}){body}', re.UNICODE)


def _compile_prefixed(kw):
    """Return a matcher when the keyword carries a recognised prefix, else None."""
    for prefix, build in ((WORD_PREFIX, _anchored), (STEM_PREFIX, _stem)):
        if kw.startswith(prefix):
            bare = kw[len(prefix):].strip()
            # A bare prefix is a config typo. Matching NOTHING is the safe
            # reading: as a positive it contributes no match, whereas an empty
            # pattern matching everything would veto an entire scan from one
            # stray colon.
            if not bare:
                return lambda lower: False
            rx = build(re.escape(bare))
            return lambda lower, rx=rx: bool(rx.search(lower))
    return None


def compile_keyword(kw):
    """Compile a lowercased title keyword into a matcher."""
    prefixed = _compile_prefixed(kw)
    if prefixed:
        return prefixed
    if re.fullmatch(r'[a-z]{2,3}', kw):
        rx = _anchored(re.escape(kw))
        return lambda lower: bool(rx.search(lower))
    return lambda lower: kw in lower


def compile_content_keyword(kw):
    """Compile a lowercased description keyword into a matcher.

    Unlike titles there is no automatic anchoring of short keywords: a 2-3
    letter run inside a paragraph of prose is routinely intended ("aws", "gcp",
    "sql", "go"), whereas "COO" inside "Coordinator" never is.
    """
    return _compile_prefixed(kw) or (lambda lower: kw in lower)


def compile_positive(keyword):
    """Compile one positive entry, honouring " + " AND-groups."""
    if not AND_SEPARATOR.search(keyword):
        return compile_keyword(keyword)
    terms = [t.strip() for t in AND_SEPARATOR.split(keyword) if t.strip()]
    if not terms:
        return compile_keyword(keyword)
    # Each term keeps compile_keyword's own rule, so a short term like "vp" is
    # still anchored and cannot hit inside another word.
    matchers = [compile_keyword(t) for t in terms]
    return lambda lower: all(m(lower) for m in matchers)


def _normalize(entries, compile_fn):
    if not isinstance(entries, (list, tuple)):
        entries = [e for e in re.split(r'[,\n]', str(entries or '')) if e]
    out = []
    for k in entries:
        if not isinstance(k, str):
            continue
        k = k.strip().lower()
        if k:
            out.append(compile_fn(k))
    return out


def build_title_filter(positive=None, negative=None):
    """Compile a whole title filter into one predicate.

    AND-groups are a positive-side feature only: on the negative side an entry
    is a veto, and " + " there would mean "reject when both appear", which is
    more clearly written as two entries.
    """
    pos = _normalize(positive, compile_positive)
    neg = _normalize(negative, compile_keyword)

    def predicate(title):
        lower = str(title or '').lower()
        # An empty positive list is "no positive constraint", not "match
        # nothing": a negative-only filter is a legitimate config.
        has_positive = not pos or any(m(lower) for m in pos)
        return has_positive and not any(m(lower) for m in neg)

    return predicate


def build_content_filter(positive=None, negative=None):
    """The same shape as build_title_filter, matched against the description."""
    pos = _normalize(positive, compile_content_keyword)
    neg = _normalize(negative, compile_content_keyword)

    def predicate(text):
        lower = str(text or '').lower()
        has_positive = not pos or any(m(lower) for m in pos)
        return has_positive and not any(m(lower) for m in neg)

    return predicate
