import sqlite3, httpx, re, json
from bs4 import BeautifulSoup
from .core import db, get_profile, get_prefs, score_job, now, uuid

def save_job(title,company,location,url,description,source='manual',ats='unknown',posted_at=None):
    """Insert a job, or return the existing id when the URL was already seen."""
    p=get_profile() or {}; prefs=get_prefs(); score,reasons=score_job(description,p.get('resume_text',''),prefs)
    jid=uuid.uuid4().hex; c=db()
    try:
        # Columns are listed explicitly so later schema migrations cannot break this insert.
        c.execute('INSERT INTO jobs(id,title,company,location,url,source,ats,description,posted_at,match_score,'
                  'match_reasons,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (jid,(title or '')[:300],(company or '')[:200],(location or '')[:300],url,source,ats,
                   (description or '')[:100000],posted_at,score,json.dumps(reasons),'NEW',now()))
        c.commit()
    except sqlite3.IntegrityError:
        row=c.execute('SELECT id FROM jobs WHERE url=?',(url,)).fetchone()
        if row: jid=row['id']
    finally:
        c.close()
    return jid

# Greenhouse and Lever fetching now lives in providers.py alongside the other
# nine boards. Keeping a second copy here is the drift that costs correctness:
# the two would diverge and a company would be scanned differently depending on
# which path reached it.

def import_url(url):
    r=httpx.get(url,timeout=30,follow_redirects=True,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status(); s=BeautifulSoup(r.text,'html.parser'); text=s.get_text('\n',strip=True)
    title=(s.find('h1').get_text(' ',strip=True) if s.find('h1') else (s.title.get_text(' ',strip=True) if s.title else 'Imported Job'))
    return save_job(title,'', '',str(r.url),text,'url','unknown')
