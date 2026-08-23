import asyncio, re, json
from playwright.async_api import async_playwright

LABEL_WORDS=['name','full name','email','phone','linkedin','github','location','city','address','cover letter','resume','why','summary']
async def inspect_and_fill(url, answers, resume_path=None, headless=False):
    results=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=headless)
        page=await browser.new_page()
        await page.goto(url,wait_until='domcontentloaded',timeout=60000)
        await page.wait_for_timeout(1500)
        fields=await page.locator('input,textarea,select').all()
        for el in fields:
            try:
                typ=(await el.get_attribute('type') or '').lower(); name=(await el.get_attribute('name') or '').lower(); aria=(await el.get_attribute('aria-label') or '').lower(); ph=(await el.get_attribute('placeholder') or '').lower()
                key=next((k for k in answers if k in ' '.join([name,aria,ph])),None)
                if key and typ not in ('file','hidden','submit','button','checkbox','radio'):
                    val=str(answers[key]); await el.fill(val); results.append({'field':name or aria or ph,'filled':True,'source':key})
                elif typ=='file' and resume_path:
                    await el.set_input_files(resume_path); results.append({'field':name or 'file','filled':True,'source':'resume'})
            except Exception as e: results.append({'error':str(e)})
        screenshot=await page.screenshot(full_page=True)
        await browser.close()
    return {'fields':results,'screenshot_bytes':screenshot}
