"""Human-safe ATS browser agent.
It fills common fields, uploads documents, detects security challenges, and can submit only when auto_apply is explicitly enabled.
It never bypasses CAPTCHA/MFA or anti-bot controls.
"""
import re, json, os, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHALLENGE_RE = re.compile(r"captcha|recaptcha|hcaptcha|verify you are human|one-time password|otp|multi-factor|mfa|two-factor|2fa", re.I)
SUBMIT_RE = re.compile(r"submit application|submit|apply", re.I)

FIELD_ALIASES = {
    "name": ["full name", "name", "legal name"], "first_name": ["first name", "given name"],
    "last_name": ["last name", "surname", "family name"], "email": ["email", "e-mail"],
    "phone": ["phone", "mobile", "telephone"], "linkedin": ["linkedin"], "github": ["github"],
    "city": ["city"], "location": ["location", "address"], "cover_letter": ["cover letter", "coverletter"],
    "why_company": ["why this company", "why company", "why do you want to work"],
    "why_role": ["why this role", "why are you interested"], "salary": ["salary", "compensation", "desired pay"],
    "work_authorization": ["work authorization", "authorized to work", "legally authorized"],
    "sponsorship": ["sponsorship", "visa sponsorship", "require sponsorship"],
}

def normalize(s): return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()

def infer_key(label):
    n=normalize(label)
    for k, aliases in FIELD_ALIASES.items():
        if any(a in n for a in aliases): return k
    return None

async def run_application(url, profile, answers, resume_path, cover_letter=None, auto_submit=False, headless=True):
    result={"url":url,"status":"STARTED","fields":[],"challenges":[],"submitted":False,"screenshots":[]}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=headless)
        context=await browser.new_context()
        page=await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1200)
            text=(await page.locator("body").inner_text())[:30000]
            if CHALLENGE_RE.search(text):
                result["status"]="SECURITY_CHALLENGE"; result["challenges"].append("Security challenge detected; user action required.")
                return result
            elements=await page.locator("input, textarea, select").all()
            for el in elements:
                try:
                    typ=(await el.get_attribute("type") or "").lower()
                    if typ in {"hidden","submit","button","image","reset"}: continue
                    label=" ".join(filter(None,[await el.get_attribute("name"),await el.get_attribute("aria-label"),await el.get_attribute("placeholder")]))
                    key=infer_key(label)
                    if typ=="file":
                        if resume_path and Path(resume_path).exists():
                            await el.set_input_files(resume_path); result["fields"].append({"field":label,"value":"<resume uploaded>"})
                        continue
                    if not key: continue
                    value=answers.get(key) or profile.get(key)
                    if key=="name" and not value: value=profile.get("name")
                    if key=="cover_letter": value=cover_letter
                    if value is None: continue
                    if typ in {"checkbox","radio"}:
                        continue
                    if await el.is_visible():
                        if await el.evaluate("e => e.tagName.toLowerCase()") == "select":
                            try: await el.select_option(label=str(value))
                            except Exception: await el.select_option(value=str(value))
                        else: await el.fill(str(value))
                        result["fields"].append({"field":label,"key":key,"filled":True})
                except Exception as e: result["fields"].append({"field":"unknown","error":str(e)})
            result["status"]="READY_TO_SUBMIT"
            shot=await page.screenshot(full_page=True); result["screenshot_bytes"]=shot
            if auto_submit:
                text=(await page.locator("body").inner_text())[:30000]
                if CHALLENGE_RE.search(text):
                    result["status"]="SECURITY_CHALLENGE"; return result
                buttons=page.get_by_role("button")
                count=await buttons.count()
                submitted=False
                for i in range(count):
                    b=buttons.nth(i)
                    name=await b.inner_text()
                    if SUBMIT_RE.search(name or "") and await b.is_visible():
                        await b.click(); submitted=True; break
                if not submitted:
                    links=page.get_by_role("link")
                    for i in range(await links.count()):
                        a=links.nth(i); name=await a.inner_text()
                        if SUBMIT_RE.search(name or "") and await a.is_visible(): await a.click(); submitted=True; break
                if submitted:
                    await page.wait_for_timeout(1500)
                    final=(await page.locator("body").inner_text())[:20000]
                    if CHALLENGE_RE.search(final): result["status"]="SECURITY_CHALLENGE"
                    else: result["status"]="SUBMITTED"; result["submitted"]=True
            return result
        except Exception as e:
            result["status"]="ERROR"; result["error"]=str(e); return result
        finally:
            await browser.close()
