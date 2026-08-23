import httpx, re, json
from bs4 import BeautifulSoup
from .core import db, get_profile, get_prefs, score_job, now, uuid

def save_job(title,company,location,url,description,source='manual',ats='unknown',posted_at=None):
    p=get_profile() or {}; prefs=get_prefs(); score,reasons=score_job(description,p.get('resume_text',''),prefs)
    jid=uuid.uuid4().hex; c=db()
    try:
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,title[:300],company[:200],location[:300],url,source,ats,description[:100000],posted_at,score,json.dumps(reasons),'NEW',now())); c.commit()
    except Exception:
        row=c.execute('SELECT id FROM jobs WHERE url=?',(url,)).fetchone(); jid=row['id'] if row else jid
    c.close(); return jid

def greenhouse(company,slug):
    url=f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'
    r=httpx.get(url,timeout=30); r.raise_for_status(); data=r.json(); n=0
    for j in data.get('jobs',[]):
        save_job(j.get('title',''),company,j.get('location',{}).get('name',''),j.get('absolute_url',''),BeautifulSoup(j.get('content',''),'html.parser').get_text('\n',strip=True),'greenhouse','greenhouse',j.get('updated_at')); n+=1
    return n

def lever(company,slug):
    url=f'https://api.lever.co/v0/postings/{slug}?mode=json'
    r=httpx.get(url,timeout=30); r.raise_for_status(); n=0
    for j in r.json():
        desc=(j.get('descriptionPlain') or '')+'\n'+ '\n'.join(x.get('content','') for x in j.get('lists',[]))
        save_job(j.get('text',''),company,(j.get('categories') or {}).get('location',''),j.get('hostedUrl',''),desc,'lever','lever',j.get('createdAt')); n+=1
    return n

def import_url(url):
    r=httpx.get(url,timeout=30,follow_redirects=True,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status(); s=BeautifulSoup(r.text,'html.parser'); text=s.get_text('\n',strip=True)
    title=(s.find('h1').get_text(' ',strip=True) if s.find('h1') else (s.title.get_text(' ',strip=True) if s.title else 'Imported Job'))
    return save_job(title,'', '',str(r.url),text,'url','unknown')
