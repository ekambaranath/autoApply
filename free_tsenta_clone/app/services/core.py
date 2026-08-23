import json, os, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[2]; DATA=ROOT/'data'; STORAGE=ROOT/'storage'; DATA.mkdir(exist_ok=True); STORAGE.mkdir(exist_ok=True)
DB=DATA/'career_agent.db'

def now(): return datetime.now(timezone.utc).isoformat()
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY,name TEXT,email TEXT,phone TEXT,location TEXT,linkedin TEXT,github TEXT,resume_text TEXT,resume_file TEXT,created_at TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS preferences(id INTEGER PRIMARY KEY,roles TEXT,locations TEXT,remote TEXT,min_salary INTEGER,max_salary INTEGER,work_auth TEXT,sponsorship TEXT,excluded_companies TEXT,keywords TEXT,auto_apply INTEGER DEFAULT 0,review_required INTEGER DEFAULT 1,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,title TEXT,company TEXT,location TEXT,url TEXT UNIQUE,source TEXT,ats TEXT,description TEXT,posted_at TEXT,match_score REAL,match_reasons TEXT,status TEXT DEFAULT 'NEW',created_at TEXT);
    CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY,job_id TEXT,status TEXT,tailored_resume TEXT,cover_letter TEXT,answers TEXT,receipt TEXT,created_at TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS resume_versions(id TEXT PRIMARY KEY,job_id TEXT,content TEXT,changes TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,application_id TEXT,event_type TEXT,payload TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY,company TEXT,platform TEXT,slug TEXT,url TEXT,active INTEGER DEFAULT 1,created_at TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    '''); c.commit(); c.close()
init_db()

def get_profile():
    c=db(); r=c.execute('SELECT * FROM profile ORDER BY id DESC LIMIT 1').fetchone(); c.close(); return dict(r) if r else None

def get_prefs():
    c=db(); r=c.execute('SELECT * FROM preferences ORDER BY id DESC LIMIT 1').fetchone(); c.close(); return dict(r) if r else {}

def terms(text):
    stop=set('the and for with from that this your our are you into using have has will role work team years experience required preferred about their they them who what when where how'.split())
    return {x for x in re.findall(r'[a-zA-Z][a-zA-Z0-9+#.-]{1,}',(text or '').lower()) if len(x)>2 and x not in stop}

def score_job(desc,resume,prefs=None):
    d,r=terms(desc),terms(resume); overlap=sorted(d&r,key=lambda x:(len(x),x),reverse=True)
    base=25+min(55, len(overlap)/max(1,min(len(d),100))*100)
    pref=prefs or {}; pterms=terms(' '.join([pref.get('roles',''),pref.get('keywords',''),pref.get('locations','')]))
    pref_hits=len(pterms & d); score=min(99,round(base+min(20,pref_hits*2),1))
    reasons=[]
    if overlap: reasons.append('Resume/JD overlap: '+', '.join(overlap[:14]))
    if pref_hits: reasons.append(f'Preference/role signals matched: {pref_hits}')
    if not overlap: reasons.append('Low direct evidence overlap; review manually')
    return score,reasons

def audit(app_id,event,payload):
    c=db(); c.execute('INSERT INTO events VALUES(?,?,?,?,?)',(uuid.uuid4().hex,app_id,event,json.dumps(payload,ensure_ascii=False),now())); c.commit(); c.close()

def llm(prompt):
    provider=os.getenv('LLM_PROVIDER','ollama').lower()
    if provider=='ollama':
        try:
            r=httpx.post(os.getenv('OLLAMA_BASE_URL','http://localhost:11434')+'/api/generate',json={'model':os.getenv('OLLAMA_MODEL','llama3.1:8b'),'prompt':prompt,'stream':False},timeout=180); r.raise_for_status(); return r.json().get('response','')
        except Exception: return ''
    if provider=='openai_compatible':
        try:
            r=httpx.post(os.getenv('LLM_BASE_URL','https://api.openai.com/v1')+'/chat/completions',headers={'Authorization':'Bearer '+os.getenv('LLM_API_KEY','')},json={'model':os.getenv('LLM_MODEL','gpt-4o-mini'),'messages':[{'role':'user','content':prompt}],'temperature':.15},timeout=180); r.raise_for_status(); return r.json()['choices'][0]['message']['content']
        except Exception: return ''
    return ''
