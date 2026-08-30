"""Zero-dependency background scheduler using a daemon thread."""
import threading, time, os
from .discovery_plus import scan_watchlist

_stop=threading.Event(); _thread=None

def interval_minutes(): return int(os.getenv('SCAN_INTERVAL_MINUTES','30'))

def status():
    return {'running':bool(_thread and _thread.is_alive()),'interval_minutes':interval_minutes()}

def _loop():
    interval=interval_minutes()*60
    # Wait first so a server restart does not immediately hammer every career page.
    _stop.wait(interval)
    while not _stop.is_set():
        try: scan_watchlist(trigger='scheduler')
        except Exception: pass
        _stop.wait(interval)

def start():
    global _thread
    if _thread and _thread.is_alive(): return
    _stop.clear(); _thread=threading.Thread(target=_loop,daemon=True,name='career-agent-scanner'); _thread.start()

def stop(): _stop.set()
