"""Fuzzy role-title matching.

Adapted to Python from career-ops (MIT, (c) 2026 Santiago Fernandez de
Valderrama) — `role-matcher.mjs` and the `titleIdentityKey` helper in
`detect-reposts.mjs`. https://github.com/santifer/career-ops

Two same-company postings routinely describe the same opening under slightly
different titles, and the same requisition gets re-listed at a fresh URL. The
job store deduplicates on URL alone, so neither case is caught without this.
"""
import re
import unicodedata

SENIORITY_TOKENS = {
    'junior', 'mid', 'middle', 'senior', 'staff', 'principal', 'lead', 'head',
    'chief', 'associate', 'intern', 'entry',
}

# Seniority words that place a requisition BELOW the bare baseline title.
# "senior"/"principal" get added and dropped freely when a role is re-posted, so
# seeing one on a single side proves nothing. These are different in kind: an
# "Associate X" and a bare "X" at one company are two real openings.
SUB_BASELINE_SENIORITY = {'associate', 'junior', 'entry', 'intern'}

# Words nearly every posting shares. They may contribute to the overlap ratio
# but can never be the reason two titles match.
ROLE_STOPWORDS = {
    # seniority / level
    'junior', 'mid', 'middle', 'senior', 'staff', 'principal', 'lead', 'head',
    'chief', 'associate', 'intern', 'entry', 'level',
    # contract / mode
    'remote', 'hybrid', 'onsite', 'contract', 'contractor', 'freelance',
    'fulltime', 'parttime', 'permanent', 'temporary', 'internship',
    # generic job words
    'role', 'position', 'opportunity', 'team', 'based',
    # reposting annotations — meta noise, never part of the job itself
    'repost', 'reposted', 'relisted',
    # very common locations
    'bangalore', 'bengaluru', 'mumbai', 'delhi', 'hyderabad', 'pune', 'chennai',
    'london', 'berlin', 'paris', 'madrid', 'barcelona', 'amsterdam', 'dublin',
    'york', 'francisco', 'seattle', 'boston', 'austin', 'chicago', 'toronto',
    'tokyo', 'singapore', 'sydney', 'melbourne', 'lisbon', 'warsaw',
    # regions / countries
    'europe', 'emea', 'apac', 'latam', 'americas', 'india', 'spain', 'germany',
    'france', 'italy', 'canada', 'brazil', 'mexico', 'japan',
    # prepositions leaking through the length filter
    'with', 'from', 'into', 'over', 'this', 'that',
}

# Short specialty acronyms that discriminate despite their length. Broad
# two-letter buckets such as AI/ML are excluded: they appear across many
# unrelated roles.
SHORT_SPECIALTY = {
    'api', 'sre', 'sdk', 'cli', 'gpu', 'cpu',
    'ios', 'qa', 'ux', 'ui', 'ar', 'vr', 'ocr', 'crm', 'erp',
}

# Generic role-level descriptors. Two titles overlapping only here are not the
# same opening — they are merely written at the same altitude.
BASELINE_TOKENS = {
    'software', 'engineer', 'developer', 'manager', 'architect',
    'analyst', 'designer', 'consultant', 'specialist',
    'platform', 'systems', 'services',
    'backend', 'frontend', 'full', 'stack', 'fullstack',
    # "product" alone cannot identify an opening: "Product Manager - Marketplace"
    # and "Product Manager - AI" are two separate applications.
    'product',
}

# "Member of Technical Staff" is a boilerplate level prefix, not a content
# signal — the suffix decides the match. Stripped as a literal phrase so
# "member"/"technical" keep their normal weight in unrelated titles.
_MTS_PREFIX = re.compile(r'\bmember\s+of\s+technical\s+staff\b')
_SLASHED_ACRONYM = re.compile(r'\b([a-z0-9]{1,3})/([a-z0-9]{1,3})\b')
_NON_WORD = re.compile(r'[^\w\s]', re.UNICODE)


def normalize_title(value):
    """Lowercase and fold Latin accents onto their ASCII base.

    Every rule below matches ASCII vocabulary, so an accent would otherwise act
    as a word separator: "Senior" spelled with an accent split into two tokens,
    leaving a phantom no stopword list covers. Only marks sitting on an ASCII
    Latin base are folded, so Devanagari matras, Cyrillic breves and Japanese
    dakuten — where the mark carries meaning — survive untouched.
    """
    text = value if isinstance(value, str) else str(value or '')
    decomposed = unicodedata.normalize('NFD', text.lower())
    out = []
    for ch in decomposed:
        if unicodedata.category(ch) == 'Mn' and out and out[-1].isascii() and out[-1].isalpha():
            continue
        out.append(ch)
    return unicodedata.normalize('NFC', ''.join(out))


def role_tokens(role):
    """Turn a role title into the content tokens used for fuzzy matching."""
    text = normalize_title(role)
    # Replaced with a baseline token rather than blank: a bare "Member of
    # Technical Staff" would otherwise yield too few tokens for the 2-token
    # floor below, so an exact repost of it could not match itself.
    text = _MTS_PREFIX.sub(' engineer ', text)
    # Collapse slashed acronyms before punctuation is stripped, or "(CI/CD)"
    # becomes "ci cd" and both halves die to the length filter — making the one
    # qualifier that separates two sibling requisitions invisible.
    text = _SLASHED_ACRONYM.sub(r'\1\2', text)
    text = _NON_WORD.sub(' ', text)
    return [w for w in text.split()
            if (len(w) > 3 or w in SHORT_SPECIALTY) and w not in ROLE_STOPWORDS]


def _seniorities(title):
    return {w for w in _NON_WORD.sub(' ', normalize_title(title)).split()
            if w in SENIORITY_TOKENS}


def role_fuzzy_match(a, b):
    """Whether two role titles likely describe the same opening.

    Requires two shared tokens, at least one of them not merely baseline job
    vocabulary, and a Jaccard overlap of 0.6+. This keeps genuine reposts while
    leaving siblings such as "Full Stack Engineer, Foundation" and "Full Stack
    Engineer, Guarded Releases" as separate applications.
    """
    text_a = str(a or '').strip().lower()
    text_b = str(b or '').strip().lower()
    # Identical titles always match, even one that tokenizes to nothing —
    # tokenization can never be why an exact repost fails to dedupe.
    if text_a and text_a == text_b:
        return True

    sen_a, sen_b = _seniorities(a), _seniorities(b)
    if sen_a and sen_b:
        # Both state a level, so they must agree on at least one.
        if not (sen_a & sen_b):
            return False
    elif sen_a or sen_b:
        # Exactly one states a level. The tokenizer drops seniority as a
        # stopword, so "Associate Product Manager, Team" and "Product Manager,
        # Team" would otherwise score a perfect ratio and collapse two real
        # requisitions. A sub-baseline qualifier is a level disagreement.
        lone = sen_a or sen_b
        if lone & SUB_BASELINE_SENIORITY:
            return False

    words_a = list(dict.fromkeys(role_tokens(a)))
    words_b = list(dict.fromkeys(role_tokens(b)))
    if not words_a or not words_b:
        return False

    set_b = set(words_b)
    overlap = [w for w in words_a if w in set_b]
    if len(overlap) < 2:
        return False
    # Roles sharing only generic descriptors like [software, engineer] are not
    # the same opening.
    if not [w for w in overlap if w not in BASELINE_TOKENS]:
        return False

    # A generic base title carries no suffix to counterbalance a specialized
    # sibling's extra word, so shared tokens alone can clear the threshold even
    # though that extra word is exactly what separates two postable openings
    # ("Senior Analytics Engineer" vs "... , People Analytics"). When one token
    # set is a strict subset of the other, treat a non-baseline extra as a
    # specialization marker and keep the titles distinct.
    smaller, larger = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    if len(larger) > len(smaller) and len(overlap) == len(smaller):
        smaller_set = set(smaller)
        if [w for w in larger if w not in smaller_set and w not in BASELINE_TOKENS]:
            return False

    # True set-based Jaccard. Dividing by the smaller title inflates matches for
    # roles sharing a long generic prefix but differing in specialty.
    union = len(set(words_a) | set(words_b))
    return len(overlap) / union >= 0.6


def title_identity_key(title):
    """An order-insensitive key grouping spellings of one title together.

    Used for repost clustering, where an equality key replaces pairwise
    similarity: a large employer accumulates thousands of distinct titles, and
    comparing every pair is quadratic. Bucketing on a key is one linear pass —
    and it is also more correct here, since pairwise similarity merged sibling
    requisitions.
    """
    raw = str(title or '').strip()
    words = [w for w in re.sub(r'[^\w]+', ' ', normalize_title(raw), flags=re.UNICODE).split() if w]
    if not words:
        return raw.lower()
    return ' '.join(sorted(set(words)))
