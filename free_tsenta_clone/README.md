# Open Career Agent — autonomous, local-first Tsenta-style system

Independent implementation inspired by publicly described career-agent capabilities. It is **not affiliated with Tsenta** and does not use Tsenta proprietary code/assets.

## Deep-research feature map implemented
Based on Tsenta's public pages and YC profile, the system targets the same four-stage loop: **Find → Prep → Apply → Track**. Tsenta publicly describes direct career-page monitoring, per-role resume/cover-letter tailoring with diff visibility, ATS form filling/submission, receipts, reply routing, Chrome extension, and MCP/CLI. This project implements the local foundations for those capabilities.

### Included now
- Local SQLite profile, preferences, jobs, applications, receipts and audit events
- PDF/DOCX/TXT resume ingestion
- Job URL import + Chrome extension import
- Greenhouse + Lever API discovery
- Generic career-page crawler for watchlist companies
- 30-minute background discovery scheduler
- Match scoring + exclusions + configurable threshold
- LLM resume tailoring + cover letter + screening answers
- Anti-fabrication policy with `NEEDS_USER_INPUT`
- Per-job resume versions and change log
- Playwright ATS browser agent
- Common-field inference for name/email/phone/LinkedIn/GitHub/location/authorization/sponsorship/cover letter
- Resume upload detection
- Security challenge detection; CAPTCHA/MFA/OTP always stops for the user
- Explicit approval gate
- Optional opt-in auto-submit
- Application receipt/audit trail
- MCP server with job/application/profile tools
- CSV tracker export
- Responsive dashboard
- Optional local Ollama — no paid AI API required

## Install
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Run
```bash
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000`.

## Free local AI
Install Ollama and:
```bash
ollama pull llama3.1:8b
```
The app defaults to Ollama. No paid LLM key is required.

## Autonomous discovery
Add watchlist entries through the API. Greenhouse and Lever use their public job APIs. Other career pages use a best-effort crawler. The scheduler runs every 30 minutes while the local server is running.

## MCP
```bash
pip install mcp
python mcp/server.py
```
Expose the server to an MCP-compatible client using its normal stdio configuration. The tools are deliberately small: list matches, add jobs, inspect queue, and read non-sensitive profile metadata.

## Chrome extension
Load the `extension/` directory as an unpacked Chrome extension. With the local server running, click the extension on a job page. It sends the page URL into the local agent.

## ATS behavior
The Playwright agent is intentionally conservative. It fills recognizable fields and uploads the resume. If it sees CAPTCHA, reCAPTCHA, hCaptcha, OTP, MFA, 2FA or similar security controls, it stops. It does not attempt to defeat security controls or hide automation. Auto-submit is disabled unless explicitly requested in the UI/API.

## Production hardening still needed for true SaaS scale
- encrypted credential vault / OS keychain
- robust per-ATS adapters and regression tests for Workday, Greenhouse, Lever, Ashby, iCIMS, SmartRecruiters, etc.
- OAuth Gmail/Outlook integration for reply routing
- queue backend (Redis/Celery/Temporal) for multi-worker scale
- browser-profile/session persistence and user-login handoff
- Chrome extension DOM extraction rather than URL-only fallback
- mobile/desktop clients
- evaluation harness for job-match precision, resume factuality and form-field accuracy
- rate limits, retries, idempotency, observability and encrypted backups

## Safety / compliance
Use only on job applications you are authorized to submit. Respect site terms, rate limits and robots/access restrictions. Never bypass CAPTCHA, MFA, OTP, login controls or other security mechanisms. Review generated content and factual claims before enabling automatic submission.
