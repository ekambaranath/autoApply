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

## Running in GitHub Codespaces

A devcontainer is included, so **Code → Codespaces → Create codespace on main** installs everything and builds the dashboard automatically. When it finishes:

```bash
cd free_tsenta_clone
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is required. Codespaces only forwards ports bound to all interfaces — the default `127.0.0.1` is reachable inside the container but produces a dead forwarded URL.

Port 8000 forwards automatically and opens in a browser tab.

**Configure it** with a `.env` in `free_tsenta_clone/` (copy `.env.example`; it is gitignored), or for anything secret use **Codespaces secrets** — repo Settings → Secrets and variables → Codespaces — which arrive as environment variables and never touch the repo.

Three things differ from running locally:

- **Use a hosted model, not Ollama.** A 2-core Codespace does not have the RAM to run an 8B model; see *The AI model* below.
- **Keep the forwarded port private.** It defaults to private, which is right — the dashboard exposes your resume, contact details and application history with no login. Do not switch it to public.
- **ATS form-filling may be blocked.** Playwright runs from a datacenter IP, which some ATS anti-bot systems reject. Discovery, matching, tailoring and tracking are unaffected; only the browser agent is. Run that part locally if it matters.

If you would rather not use the devcontainer, the steps in *Install* work as-is once you add `--host 0.0.0.0`.

## The AI model

Used to tailor your resume, write cover letters and answer screening questions. **Setup → AI model** shows what is configured and has a **Test the model** button that reports the real error — wrong slug, missing key, exhausted quota, timeout — instead of silently falling back.

### Option 1 — local, private, free

```bash
ollama pull llama3.1:8b
```

The default. Nothing leaves your machine.

### Option 2 — hosted via OpenRouter

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-...
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
LLM_TIMEOUT=600
```

Any OpenAI-compatible endpoint works; OpenRouter just happens to have a free tier.

**Choosing a model.** This prompt is harder than it looks: it holds ~30k tokens of resume + job description, rewrites the resume *without inventing anything*, and returns it all as valid JSON. So you need:

| Requirement | Why |
| --- | --- |
| Context ≥ 32k | `prepare` sends up to 100k characters |
| Output ≥ 8k tokens | A truncated resume is invalid JSON, and falls back silently |
| Good instruction-following | Weak models invent a metric or title to make the resume "better" — which defeats the anti-fabrication guarantee |
| Throughput ≥ ~20 t/s | Below that, a 3k-token response exceeds even the 600s timeout |

That last row is the trap: the cheapest models are often the slowest, and a 7 t/s model needs ~7 minutes for one resume.

The free roster churns — it dropped from 15 to 14 models in a single week — so check what exists before committing:

```bash
curl -s https://openrouter.ai/api/v1/models \
  | jq -r '.data[] | select(.pricing.prompt=="0")
           | "\(.id)\t\(.context_length)"'
```

Free tiers are rate-limited (~20 req/min, ~200 req/day), served at low priority, and **may train on what you send** — and every request carries your name, email, phone and location. If that matters, a cheap paid model runs about $0.004 per application.

## The dashboard

| Page | What it answers |
| --- | --- |
| **Overview** | Funnel, match-score distribution, discovery vs. applications over time, top companies and ATS breakdown |
| **Jobs** | Filterable table with per-job match reasoning and posting-quality signals |
| **Job sources** | 27 market-wide sources: turn each on or off, test one live, set the freshness cutoff |
| **Applications** | Full review flow: resume diff against your original, cover letter, screening answers, receipts, agent screenshots, event history |
| **Inbox** | Employer replies read over IMAP, classified, and applied to your application statuses |
| **Pipeline health** | Follow-ups due and overdue, advance rate per ATS, stage distribution, re-listed roles |
| **Activity** | Live feed of scan runs and agent events |
| **Setup** | Profile and resume, preferences with a title-filter tester, watchlist with automatic board detection |

Every chart has a table view, works in light and dark, and is keyboard reachable. The palette is validated for colour-vision deficiency in both themes.

## Job discovery

Two paths run on every scan, and the scheduler runs both every 30 minutes (`SCAN_INTERVAL_MINUTES`).

### Market-wide sources — no watchlist needed

**Job sources** carries 27 feeds that pull newly-posted roles across the whole market against your keywords, so fresh postings arrive without you naming a company first. Eight broad ones are on by default; turn on whichever match your market:

*Remote/global* — RemoteOK, Remotive, Himalayas, Working Nomads, We Work Remotely, Jobicy, NODESK
*Europe* — Arbeitnow, Arbeitsagentur (DE), JustJoin.it and NoFluffJobs (PL), Landing.jobs (PT), Manfred (ES), The Hub (Nordics), SolidJobs (RO)
*Americas* — The Muse (US), Get on Board (LatAm), Job Bank Canada
*APAC* — MyCareersFuture (SG), JobStreet (SEA), Yourator (TW)
*Niche* — HN "Who is hiring", EchoJobs, 4 Day Week, Cryptocurrency Jobs, LaraJobs, HigherEdJobs

Set a **freshness cutoff** to skip anything older than N days. A feed publishing no date is always kept — dropping undated rows would silently discard whole sources. Use **Test** on any source to fetch a few rows without saving.

### Company watchlist

Add a company on **Setup → Watchlist** by pasting its careers URL — the board and slug are detected automatically. Twenty ATS platforms have real adapters:

`ashby`, `bamboohr`, `breezy`, `comeet`, `eightfold`, `getro`, `greenhouse`, `join`, `jobvite`, `lever`, `oraclecloud`, `personio`, `pinpoint`, `recruitee`, `rippling`, `smartrecruiters`, `softgarden`, `teamtailor`, `workable`, `workday`

Workday, Oracle Cloud and Eightfold are addressed by their full careers URL rather than a slug — the URL carries tenant, instance and site, which a slug cannot express. Anything unrecognised falls back to a best-effort career-page crawler.

### Title filtering

Preferences take keep and reject keyword lists. A plain keyword is a substring; the prefixes narrow it:

| Entry | Matches |
| --- | --- |
| `agent` | Agentforce, Agentic **and** Reagents |
| `word:agent` | only the exact word — rejects Agentforce |
| `stem:agent` | words starting with it — keeps Agentforce, drops Reagents |
| `director + engineering` | titles containing **both** terms, in any order |

Two-to-three letter acronyms anchor automatically, so `coo` never matches "Coordinator". Use **Test the title filter** to check a filter before it silently drops a whole scan.

## Closing the loop — reading employer replies

Statuses otherwise only move when you remember to log them, which is the step that gets skipped. Point the agent at your mailbox and it reads replies, classifies them, and advances the matching application:

```bash
MAIL_IMAP_HOST=imap.gmail.com     # Gmail, Outlook and Fastmail all work
MAIL_IMAP_PORT=993
MAIL_USER=you@example.com
MAIL_PASSWORD=your-app-password   # an APP password, not your login password
MAIL_FOLDER=INBOX
```

Credentials are read from the environment and never written to the database. Gmail and Outlook require an app-specific password with 2FA enabled and reject a normal one.

**Inbox → Preview** classifies and matches without changing anything, so you can see what it would do first. The rules are deliberately conservative:

- **Rejections are matched before interviews.** A rejection routinely mentions the interview it is declining ("not moving forward to interview"), and reading that as an invitation is the costliest error here.
- An application **never moves backwards** and never leaves a terminal state.
- Anything it cannot place is reported **unmatched** rather than guessed at.
- Bulk senders (no-reply, job alerts, newsletters) are skipped entirely.
- Company matching is whole-word, so a short name like "Ai" cannot match inside "mailchimp".

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
python -m pytest tests/ -q
# or individually:
python tests/test_ported_logic.py tests/test_aggregators.py tests/test_mailbox.py tests/test_llm.py
```

122 tests cover role matching, title filtering, state folding, repost clustering, legitimacy signals, follow-up cadence, channel rates, every ATS and aggregator parser, the full IMAP sync path, and every LLM failure mode. All of them stub the network with captured payloads, so the suite runs offline.

> The adapters are verified against captured response shapes, not live endpoints — the sandbox this was built in blocks those hosts. Use **Test** on a source, or run a watchlist scan, to confirm one against the real API.

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
- `app/services/aggregators.py` — the market-wide feed endpoints (`providers/`)

career-ops is a Node/CLI-agent system with a larger provider library (78 boards) and features this project does not attempt — PDF/LaTeX CV generation, interview prep, negotiation tooling and a terminal UI. If you want those, use it directly.

**Not ported, and why.** career-ops's remaining adapters — iCIMS, SuccessFactors, Phenom, Avature, Cornerstone, Radancy, Gem, Beesite and the single-employer boards (Amazon, IBM, Tencent, Deutsche Bahn, Mercedes…) — need HTML scraping, GraphQL, or per-tenant auth handshakes. Those cannot be written correctly without hitting the live endpoint, which this build could not reach, and a fragile untested adapter is worse than none: it fails silently mid-scan. They fall through to the generic career-page crawler instead. If you want one of them, run it against the real board and the shape will be obvious.

## Production hardening still needed

- encrypted credential vault / OS keychain
- per-ATS form adapters and regression tests for Workday, iCIMS, SuccessFactors, etc.
- OAuth Gmail/Outlook integration so replies route themselves
- queue backend (Redis/Celery) for multi-worker scale
- browser-session persistence and user-login handoff
- Chrome extension DOM extraction rather than URL-only fallback
- evaluation harness for match precision, resume factuality and form-field accuracy
- rate limits, retries, idempotency, observability and encrypted backups
