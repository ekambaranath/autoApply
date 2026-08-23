import json, os, uuid
from . import __init__
from ..services.core import db, now, get_profile, get_prefs, audit, llm
from ..services.ats_agent import run_application

class CareerAgent:
    """Find -> qualify -> prep -> apply -> track orchestration."""
    def qualify(self, job):
        p=get_profile() or {}; prefs=get_prefs() or {}
        score=float(job.get('match_score') or 0)
        excluded=[x.strip().lower() for x in (prefs.get('excluded_companies') or '').split(',') if x.strip()]
        if job.get('company','').lower() in excluded: return False,'excluded company'
        return score>=float(os.getenv('AUTO_APPLY_MIN_SCORE','80')), f'score={score}'

    def queue_matches(self):
        c=db(); jobs=[dict(x) for x in c.execute("SELECT * FROM jobs WHERE status='NEW' ORDER BY match_score DESC")]; c.close(); return jobs

    def prepare_job(self, job_id):
        # Delegated to API endpoint for backwards compatibility.
        return job_id

    async def apply(self, application_id, auto_submit=False):
        c=db(); a=c.execute('SELECT a.*,j.* FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?',(application_id,)).fetchone(); c.close()
        if not a: raise ValueError('application not found')
        p=get_profile() or {}; answers=json.loads(a['answers'] or '{}')
        if any(v=='NEEDS_USER_INPUT' for v in answers.values()): return {'status':'NEEDS_USER_INPUT'}
        resume=str((__import__('pathlib').Path(__file__).resolve().parents[2]/'storage'/p.get('resume_file','')))
        result=await run_application(a['url'],p,answers,resume,a['cover_letter'],auto_submit=auto_submit,headless=True)
        t=now(); c=db(); status='SUBMITTED' if result.get('submitted') else result.get('status','READY_TO_SUBMIT'); receipt={k:v for k,v in result.items() if k!='screenshot_bytes'}; c.execute('UPDATE applications SET status=?,receipt=?,updated_at=? WHERE id=?',(status,json.dumps(receipt),t,application_id)); c.commit(); c.close(); audit(application_id,status,receipt); return result
