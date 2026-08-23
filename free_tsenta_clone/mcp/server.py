"""Optional MCP server. Install mcp to use it: pip install mcp.
Run: python mcp/server.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    raise SystemExit('Install MCP support with: pip install mcp')
from app.services.core import db, get_profile, get_prefs
from app.services.discovery import save_job

mcp=FastMCP('Open Career Agent')

@mcp.tool()
def list_matches(min_score: float=70):
    c=db(); rows=[dict(x) for x in c.execute('SELECT id,title,company,location,url,match_score,ats,status FROM jobs WHERE match_score>=? ORDER BY match_score DESC',(min_score,))]; c.close(); return rows

@mcp.tool()
def add_job(title:str, company:str, url:str, description:str, location:str=''):
    return {'job_id':save_job(title,company,location,url,description,'mcp','unknown')}

@mcp.tool()
def get_application_queue():
    c=db(); rows=[dict(x) for x in c.execute('SELECT a.id,j.title,j.company,j.url,j.match_score,a.status FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.created_at DESC')]; c.close(); return rows

@mcp.tool()
def profile():
    p=get_profile() or {}; return {k:v for k,v in p.items() if k!='resume_text'}

if __name__=='__main__': mcp.run()
