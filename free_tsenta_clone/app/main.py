import csv, io, json, os, re, uuid, asyncio
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document
from .services.core import *
from .services.discovery import save_job, greenhouse, lever, import_url
from .services.discovery_plus import scan_watchlist
from .services.ats_agent import run_application
from .services.scheduler import start as start_scheduler, stop as stop_scheduler

app=FastAPI(title='Open Career Agent',version='3.0.0')
ROOT=Path(__file__).resolve().parent.parent

def extract(name,data):
    if name.lower().endswith('.pdf'): return '\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages)
    if name.lower().endswith('.docx'): return '\n'.join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    return data.decode('utf-8','ignore')

@app.on_event('startup')
def boot(): start_scheduler()
@app.on_event('shutdown')
def shutdown(): stop_scheduler()
@app.get('/')
def home(): return FileResponse(ROOT/'static'/'index.html')
@app.get('/api/health')
def health(): return {'ok':True,'version':'3.0.0','local_first':True,'scheduler':True}
@app.get('/api/profile')
def profile_api(): return get_profile() or {}
@app.post('/api/profile')
def profile_save(name:str=Form(''),email:str=Form(''),phone:str=Form(''),location:str=Form(''),linkedin:str=Form(''),github:str=Form(''),resume:UploadFile=File(...)):
    raw=resume.file.read(); text=extract(resume.filename,raw); fn=uuid.uuid4().hex+'_'+Path(resume.filename).name; (STORAGE/fn).write_bytes(raw); t=now(); c=db(); c.execute('DELETE FROM profile'); c.execute('INSERT INTO profile(name,email,phone,location,linkedin,github,resume_text,resume_file,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(name,email,phone,location,linkedin,github,text,fn,t,t)); c.commit(); c.close(); return {'ok':True,'characters':len(text)}
class PrefIn(BaseModel): roles:str=''; locations:str=''; remote:str='Any'; min_salary:int=0; max_salary:int=0; work_auth:str=''; sponsorship:str='Any'; excluded_companies:str=''; keywords:str=''; auto_apply:bool=False; review_required:bool=True
@app.get('/api/preferences')
def prefs_get(): return get_prefs()
@app.post('/api/preferences')
def prefs_save(x:PrefIn):
    c=db(); c.execute('DELETE FROM preferences'); c.execute('INSERT INTO preferences(roles,locations,remote,min_salary,max_salary,work_auth,sponsorship,excluded_companies,keywords,auto_apply,review_required,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(x.roles,x.locations,x.remote,x.min_salary,x.max_salary,x.work_auth,x.sponsorship,x.excluded_companies,x.keywords,int(x.auto_apply),int(x.review_required),now())); c.commit(); c.close(); return {'ok':True}
class JobIn(BaseModel): title:str; company:str=''; location:str=''; url:str; description:str; source:str='manual'; ats:str='unknown'
@app.post('/api/jobs')
def job_add(x:JobIn): return {'id':save_job(x.title,x.company,x.location,x.url,x.description,x.source,x.ats),'ok':True}
class PageJob(BaseModel): url:str; title:str=''; text:str=''
@app.post('/api/jobs/from-page')
def job_from_page(x:PageJob):
    text=x.text or ''
    if len(text)<300:
        try: text=import_url(x.url); return {'id':text,'ok':True}
        except: pass
    return {'id':save_job(x.title or 'Imported role','', '',x.url,text,'chrome_extension','unknown'),'ok':True}
@app.post('/api/jobs/import-url')
def job_import(url:str=Form(...)): return {'id':import_url(url),'ok':True}
@app.post('/api/discovery/sync')
def sync(): return scan_watchlist()
class WatchIn(BaseModel): company:str; platform:str; slug:str=''; url:str=''
@app.post('/api/watchlist')
def watch_add(x:WatchIn):
    c=db(); c.execute('INSERT INTO watchlist(company,platform,slug,url,created_at) VALUES(?,?,?,?,?)',(x.company,x.platform,x.slug,x.url,now())); c.commit(); c.close(); return {'ok':True}
@app.get('/api/watchlist')
def watch():
    c=db(); r=[dict(x) for x in c.execute('SELECT * FROM watchlist ORDER BY company')]; c.close(); return r
@app.get('/api/jobs')
def jobs():
    c=db(); r=[dict(x) for x in c.execute('SELECT * FROM jobs ORDER BY match_score DESC,created_at DESC')]; c.close(); [x.update(match_reasons=json.loads(x['match_reasons'])) for x in r]; return r
class Prep(BaseModel): job_id:str
@app.post('/api/applications/prepare')
def prepare(x:Prep):
    p=get_profile(); c=db(); j=c.execute('SELECT * FROM jobs WHERE id=?',(x.job_id,)).fetchone(); c.close()
    if not p or not j: raise HTTPException(404,'Profile or job missing')
    prompt=f'''You are a strict career-agent editor. Use ONLY facts in RESUME. Never invent metrics, employers, titles, dates, skills, degrees, authorization or experience. Return valid JSON with tailored_resume, cover_letter, answers, change_log. Tailored resume must preserve factual claims and only reorder/rephrase. answers is a JSON object. Unknown personal facts must be NEEDS_USER_INPUT. change_log is an array of concise changes.\nRESUME:\n{p['resume_text'][:50000]}\nJOB:\n{j['description'][:50000]}'''
    raw=llm(prompt); data={}
    if raw:
        m=re.search(r'\{.*\}',raw,re.S)
        try: data=json.loads(m.group(0))
        except: pass
    if not data: data={'tailored_resume':p['resume_text'],'cover_letter':f'Dear Hiring Team,\n\nI am applying for the {j["title"]} role at {j["company"] or "your company"}. My background aligns with the requirements described in the posting, and I would welcome the opportunity to discuss the role.\n\nRegards,\n{p["name"]}','answers':{'work_authorization':'NEEDS_USER_INPUT','sponsorship':'NEEDS_USER_INPUT'},'change_log':['Fallback: original resume preserved.']}
    aid=uuid.uuid4().hex;t=now();c=db();c.execute('INSERT INTO applications VALUES(?,?,?,?,?,?,?,?,?)',(aid,x.job_id,'READY_FOR_REVIEW',data.get('tailored_resume',''),data.get('cover_letter',''),json.dumps(data.get('answers',{})),json.dumps({'prepared_at':t,'change_log':data.get('change_log',[])}),t,t));c.execute('INSERT INTO resume_versions VALUES(?,?,?,?,?)',(uuid.uuid4().hex,x.job_id,data.get('tailored_resume',''),json.dumps({'generated':True,'change_log':data.get('change_log',[])}),t));c.commit();c.close();audit(aid,'PREPARED',{'job_id':x.job_id,'change_log':data.get('change_log',[])});return {'id':aid,'status':'READY_FOR_REVIEW',**data}
@app.get('/api/applications')
def apps():
    c=db();r=[dict(x) for x in c.execute('SELECT a.*,j.title,j.company,j.location,j.url,j.ats,j.match_score FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.created_at DESC')];c.close();return r
class ApplyIn(BaseModel): application_id:str; confirm:bool=False; auto_submit:bool=False
@app.post('/api/applications/run')
async def run_apply(x:ApplyIn):
    if not x.confirm: raise HTTPException(400,'Explicit confirmation required')
    c=db(); a=c.execute('SELECT a.*,j.* FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?',(x.application_id,)).fetchone(); c.close()
    if not a: raise HTTPException(404,'Application not found')
    p=get_profile() or {}; answers=json.loads(a['answers'] or '{}')
    if any(v=='NEEDS_USER_INPUT' for v in answers.values()): raise HTTPException(409,'Application has NEEDS_USER_INPUT fields')
    resume=str(STORAGE/p.get('resume_file',''))
    result=await run_application(a['url'],p,answers,resume,a['cover_letter'],auto_submit=x.auto_submit,headless=True)
    t=now(); safe={k:v for k,v in result.items() if k!='screenshot_bytes'}; status=result.get('status','READY_TO_SUBMIT'); c=db();c.execute('UPDATE applications SET status=?,receipt=?,updated_at=? WHERE id=?',(status,json.dumps(safe),t,x.application_id));c.commit();c.close();audit(x.application_id,status,safe);return {'status':status,'submitted':result.get('submitted',False),'receipt':safe}
@app.post('/api/applications/approve')
def approve(x:ApplyIn):
    if not x.confirm: raise HTTPException(400,'Explicit confirmation required')
    c=db();r=c.execute('SELECT * FROM applications WHERE id=?',(x.application_id,)).fetchone();
    if not r:c.close();raise HTTPException(404,'Application not found')
    t=now();receipt={'approved_at':t,'next_step':'run /api/applications/run','security_note':'CAPTCHA/MFA challenges require user action.'};c.execute('UPDATE applications SET status=?,receipt=?,updated_at=? WHERE id=?',('APPROVED',json.dumps(receipt),t,x.application_id));c.commit();c.close();audit(x.application_id,'APPROVED',receipt);return receipt
@app.get('/api/applications/{aid}/events')
def events(aid:str):
    c=db();r=[dict(x) for x in c.execute('SELECT * FROM events WHERE application_id=? ORDER BY created_at',(aid,))];c.close();return r
@app.post('/api/agent/scan')
def agent_scan(): return {'results':scan_watchlist()}
@app.get('/api/stats')
def stats():
    c=db(); vals={}; vals['jobs']=c.execute('SELECT count(*) n FROM jobs').fetchone()['n']; vals['matches']=c.execute('SELECT count(*) n FROM jobs WHERE match_score>=70').fetchone()['n']; vals['applications']=c.execute('SELECT count(*) n FROM applications').fetchone()['n']; vals['approved']=c.execute("SELECT count(*) n FROM applications WHERE status='APPROVED'").fetchone()['n']; vals['submitted']=c.execute("SELECT count(*) n FROM applications WHERE status='SUBMITTED'").fetchone()['n']; vals['responses']=c.execute("SELECT count(*) n FROM events WHERE event_type IN ('REPLIED','INTERVIEW')").fetchone()['n'];c.close();return vals
@app.get('/api/export.csv')
def export():
    c=db();rows=c.execute('SELECT j.company,j.title,j.location,j.url,j.ats,j.match_score,a.status,a.created_at,a.updated_at FROM applications a JOIN jobs j ON j.id=a.job_id').fetchall();c.close();s=io.StringIO();w=csv.writer(s);w.writerow(['company','title','location','url','ats','match_score','status','created_at','updated_at']);w.writerows(rows);return StreamingResponse(iter([s.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=career_agent.csv'})
