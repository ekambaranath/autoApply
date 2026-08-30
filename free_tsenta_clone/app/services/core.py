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
    CREATE TABLE IF NOT EXISTS scan_runs(id TEXT PRIMARY KEY,trigger TEXT,status TEXT,jobs_found INTEGER DEFAULT 0,companies INTEGER DEFAULT 0,detail TEXT,error TEXT,started_at TEXT,finished_at TEXT);
    CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,active INTEGER DEFAULT 1,last_run TEXT,last_count INTEGER DEFAULT 0,last_error TEXT);
    CREATE TABLE IF NOT EXISTS mail_state(key TEXT PRIMARY KEY,value TEXT);
    CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
    CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score);
    '''); c.commit(); c.close()
    migrate()

def migrate():
    """Add columns introduced after the first release without dropping existing data."""
    c=db()
    for table,col,ddl in [('applications','screenshot_file','TEXT'),('applications','notes','TEXT'),
                          ('applications','followups_sent','INTEGER DEFAULT 0'),
                          ('applications','followed_up_at','TEXT'),
                          ('jobs','dismissed','INTEGER DEFAULT 0'),
                          ('preferences','excluded_titles','TEXT')]:
        cols={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
        if col not in cols: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
    c.commit(); c.close()
init_db()

def get_setting(key,default=None):
    c=db(); r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); c.close()
    return r['value'] if r else default

def set_setting(key,value):
    c=db(); c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value))); c.commit(); c.close()

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

#: Set by the last llm() call, so a misconfigured provider reports the real
#: reason instead of looking identical to a model that simply answered badly.
LLM_LAST_ERROR = None

#: Free and low-priority tiers are served slowly: a full tailored resume can be
#: several thousand tokens, and at the throughput a free tier gives you that
#: takes minutes. The old 180s default aborted mid-generation and surfaced as
#: "the model returned nothing", which is indistinguishable from a bad prompt.
DEFAULT_LLM_TIMEOUT = 600


def llm_timeout():
    try:
        return max(30, int(os.getenv('LLM_TIMEOUT', DEFAULT_LLM_TIMEOUT)))
    except ValueError:
        return DEFAULT_LLM_TIMEOUT


def llm_config():
    """What the agent will call, and why the last call failed if it did."""
    provider = os.getenv('LLM_PROVIDER', 'ollama').lower()
    return {'provider': provider,
            'model': os.getenv('OLLAMA_MODEL', 'llama3.1:8b') if provider == 'ollama'
                     else os.getenv('LLM_MODEL', 'gpt-4o-mini'),
            'base_url': os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434') if provider == 'ollama'
                        else os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'),
            'has_key': bool(os.getenv('LLM_API_KEY')) if provider != 'ollama' else True,
            'timeout': llm_timeout(),
            'last_error': LLM_LAST_ERROR}


def llm(prompt):
    """Call the configured model. Returns '' on failure, with the reason in
    LLM_LAST_ERROR so callers and the UI can tell why rather than guessing."""
    global LLM_LAST_ERROR
    provider = os.getenv('LLM_PROVIDER', 'ollama').lower()
    timeout = llm_timeout()
    try:
        if provider == 'ollama':
            r = httpx.post(os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434') + '/api/generate',
                           json={'model': os.getenv('OLLAMA_MODEL', 'llama3.1:8b'),
                                 'prompt': prompt, 'stream': False}, timeout=timeout)
            r.raise_for_status()
            LLM_LAST_ERROR = None
            return r.json().get('response', '')

        if provider == 'openai_compatible':
            key = os.getenv('LLM_API_KEY', '')
            if not key:
                LLM_LAST_ERROR = 'LLM_API_KEY is not set'
                return ''
            headers = {'Authorization': 'Bearer ' + key}
            base = os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1')
            if 'openrouter' in base:
                # OpenRouter asks callers to identify themselves; without these
                # a request still works but is deprioritised on free tiers.
                headers.update({'HTTP-Referer': 'http://localhost:8000',
                                'X-Title': 'Open Career Agent'})
            r = httpx.post(base + '/chat/completions', headers=headers,
                           json={'model': os.getenv('LLM_MODEL', 'gpt-4o-mini'),
                                 'messages': [{'role': 'user', 'content': prompt}],
                                 'temperature': .15}, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if 'choices' not in data:
                # OpenRouter reports a bad slug or an exhausted quota as a 200
                # carrying an error object, so this is not an exceptional path.
                LLM_LAST_ERROR = str(data.get('error') or data)[:400]
                return ''
            LLM_LAST_ERROR = None
            return data['choices'][0]['message']['content']

        LLM_LAST_ERROR = f'Unknown LLM_PROVIDER: {provider}'
        return ''
    except httpx.TimeoutException:
        LLM_LAST_ERROR = (f'Timed out after {timeout}s. Free tiers are slow — '
                          'raise LLM_TIMEOUT or pick a faster model.')
    except httpx.HTTPStatusError as e:
        body = (e.response.text or '')[:300]
        LLM_LAST_ERROR = f'HTTP {e.response.status_code}: {body}'
    except httpx.ConnectError as e:
        LLM_LAST_ERROR = f'Could not reach the model: {e}'
    except Exception as e:
        LLM_LAST_ERROR = f'{type(e).__name__}: {e}'
    return ''
