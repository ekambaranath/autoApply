import asyncio, re, json, hashlib
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
from .core import db, now
from .discovery import save_job

UA='OpenCareerAgent/3.0 (+local-first)'

def ats_from_url(url):
    u=url.lower()
    for name in ['workday','greenhouse','lever','ashby','rippling','icims','bamboohr','workable','jazzhr','jobvite','breezy','oracle','smartrecruiters','paylocity','ultipro','adp','dover','gem','zoho']:
        if name in u: return name
    return 'unknown'

def crawl_page(company,url):
    r=httpx.get(url,timeout=30,follow_redirects=True,headers={'User-Agent':UA}); r.raise_for_status()
    soup=BeautifulSoup(r.text,'html.parser'); text=soup.get_text('\n',strip=True)
    title=(soup.title.get_text(' ',strip=True) if soup.title else company+' careers')
    # Best-effort extraction of links that look like jobs; actual ATS adapters are preferred.
    links=[]
    for a in soup.find_all('a',href=True):
        label=a.get_text(' ',strip=True); href=a['href']
        if re.search(r'job|career|position|opening|engineer|developer|scientist|manager', label+' '+href, re.I):
            links.append((label,href))
    return title,text,links

def scan_watchlist():
    c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM watchlist WHERE active=1')]; c.close(); out=[]
    for w in rows:
        try:
            from .discovery import greenhouse, lever
            if w['platform']=='greenhouse': n=greenhouse(w['company'],w['slug'])
            elif w['platform']=='lever': n=lever(w['company'],w['slug'])
            else:
                _,_,links=crawl_page(w['company'],w['url']); n=0
                for label,href in links[:100]:
                    if href.startswith('/'): href=w['url'].rstrip('/')+href
                    if href.startswith('http'):
                        try:
                            rr=httpx.get(href,timeout=15,follow_redirects=True,headers={'User-Agent':UA}); ss=BeautifulSoup(rr.text,'html.parser')
                            desc=ss.get_text('\n',strip=True)
                            if len(desc)>500: save_job(label or 'Open role',w['company'],'',str(rr.url),desc,'career_page',ats_from_url(str(rr.url))); n+=1
                        except Exception: pass
            out.append({'company':w['company'],'count':n})
        except Exception as e: out.append({'company':w['company'],'error':str(e)})
    return out
