# Open Career Agent — autonomous, local-first job application system

Independent implementation inspired by publicly described career-agent capabilities. It is **not affiliated with Tsenta** and does not use Tsenta proprietary code/assets.

Everything runs on your machine: a FastAPI backend over SQLite, a React dashboard served from the same origin, and an optional local LLM. No account, no cloud, no paid API required.

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Build the dashboard (Node 18+)
cd frontend && npm install && npm run build && cd ..
```

## Run

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. The built dashboard is served by FastAPI on the same port, so there is one process to run.

> If you skip the frontend build, the server falls back to the legacy `static/index.html` so the API stays usable.

### Frontend development

```bash
cd frontend && npm run dev     # http://localhost:5173, proxies /api to :8000
```

## Free local AI

```bash
ollama pull llama3.1:8b
```

The app defaults to Ollama. Set `LLM_PROVIDER=openai_compatible` plus `LLM_API_KEY` / `LLM_MODEL` to use a hosted model instead. With no LLM reachable, preparation falls back to your original resume and a plain cover letter rather than inventing content.

## The dashboard

| Page | What it answers |
| --- | --- |
| **Overview** | Funnel, match-score distribution, discovery vs. applications over time, top companies and ATS breakdown |
| **Jobs** | Filterable table with per-job match reasoning and posting-quality signals |
| **Applications** | Full review flow: resume diff against your original, cover letter, screening answers, receipts, agent screenshots, event history |
| **Pipeline health** | Follow-ups due and overdue, advance rate per ATS, stage distribution, re-listed roles |
| **Activity** | Live feed of scan runs and agent events |
| **Setup** | Profile and resume, preferences with a title-filter tester, watchlist with automatic board detection |

Every chart has a table view, works in light and dark, and is keyboard reachable. The palette is validated for colour-vision deficiency in both themes.

## Job discovery

Add a company on **Setup → Watchlist** by pasting its careers URL — the board and its slug are detected automatically. Eleven ATS providers have real adapters:

`ashby`, `breezy`, `greenhouse`, `lever`, `personio`, `pinpoint`, `recruitee`, `rippling`, `smartrecruiters`, `teamtailor`, `workable`

Anything else falls back to a best-effort career-page crawler. The scheduler rescans every 30 minutes (`SCAN_INTERVAL_MINUTES`).

### Title filtering

Preferences take keep and reject keyword lists. A plain keyword is a substring; the prefixes narrow it:

| Entry | Matches |
| --- | --- |
| `agent` | Agentforce, Agentic **and** Reagents |
| `word:agent` | only the exact word — rejects Agentforce |
| `stem:agent` | words starting with it — keeps Agentforce, drops Reagents |
| `director + engineering` | titles containing **both** terms, in any order |

Two-to-three letter acronyms anchor automatically, so `coo` never matches "Coordinator". Use **Test the title filter** to check a filter before it silently drops a whole scan.

## Pipeline health

- **Follow-up cadence** — a first nudge 7 days after applying, then one more; replies get a next-day answer, interviews a thank-you. Configurable in `insights.DEFAULT_CADENCE`.
- **Re-listed roles** — the same role posted again at a fresh URL. Two listings first seen on the *same* day are concurrent requisitions, not a re-listing, so they are excluded — that single rule removes the large majority of false positives.
- **Posting signals** — upfront-fee demands, off-channel contact, evergreen "talent pool" wording, thin descriptions, missing salary. Deliberately kept **out** of the match score: whether a posting is real is a different question from whether it suits you, and averaging the two hides both.
- **Advance rate per ATS** — of what you sent through each channel, how much drew a reply.

## Safety

The Playwright agent fills recognisable fields and uploads your resume. It **stops** at CAPTCHA, reCAPTCHA, hCaptcha, OTP, MFA or 2FA and hands back to you; it never attempts to defeat a security control or hide automation. Auto-submit is off unless you explicitly request it per application, and an application with unanswered `NEEDS_USER_INPUT` fields cannot be approved or submitted.

Unknown personal facts are marked `NEEDS_USER_INPUT` rather than guessed. Review generated content before enabling submission, use it only on applications you are authorised to submit, and respect each site's terms and rate limits.

## Tests

```bash
python tests/test_ported_logic.py      # or: python -m pytest tests/ -q
```

43 tests cover role matching, title filtering, state folding, repost clustering, legitimacy signals, follow-up cadence, channel rates, and every ATS parser (against captured payloads, so no network is needed).

## MCP and the Chrome extension

```bash
pip install mcp && python mcp/server.py
```

Load `extension/` as an unpacked Chrome extension to send the current job page into the local agent.

## Attribution

Several components are adapted from [**career-ops**](https://github.com/santifer/career-ops) by Santiago Fernández de Valderrama (MIT):

- `app/services/role_match.py` — fuzzy role-title matching (`role-matcher.mjs`)
- `app/services/title_filter.py` — keyword matching with `word:`/`stem:` prefixes and AND-groups (`title-keywords.mjs`)
- `app/services/states.py` — canonical state roster (`templates/states.yml`)
- `app/services/insights.py` — repost clustering, follow-up cadence, channel rates (`detect-reposts.mjs`, `followup-cadence.mjs`, `analyze-patterns.mjs`); the posting-legitimacy signals are inspired by its Block G check
- `app/services/providers.py` — the ATS endpoint map and detect-from-URL routing (`providers/`)

career-ops is a Node/CLI-agent system with a far larger provider library (90+ boards) and features this project does not attempt — PDF/LaTeX CV generation, interview prep, negotiation tooling and a terminal UI. If you want those, use it directly.

## Production hardening still needed

- encrypted credential vault / OS keychain
- per-ATS form adapters and regression tests for Workday, iCIMS, SuccessFactors, etc.
- OAuth Gmail/Outlook integration so replies route themselves
- queue backend (Redis/Celery) for multi-worker scale
- browser-session persistence and user-login handoff
- Chrome extension DOM extraction rather than URL-only fallback
- evaluation harness for match precision, resume factuality and form-field accuracy
- rate limits, retries, idempotency, observability and encrypted backups
