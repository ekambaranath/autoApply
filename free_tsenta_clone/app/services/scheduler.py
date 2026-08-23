"""Zero-dependency background scheduler using a daemon thread."""
import threading, time, os
from .discovery_plus import scan_watchlist

_stop=threading.Event(); _thread=None

def _loop():
    interval=int(os.getenv('SCAN_INTERVAL_MINUTES','30'))*60
    while not _stop.is_set():
        try: scan_watchlist()
        except Exception: pass
        _stop.wait(interval)

def start():
    global _thread
    if _thread and _thread.is_alive(): return
    _stop.clear(); _thread=threading.Thread(target=_loop,daemon=True,name='career-agent-scanner'); _thread.start()

def stop(): _stop.set()
