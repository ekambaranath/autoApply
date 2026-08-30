"""Zero-dependency background scanner using a daemon thread."""
import os
import threading

_stop = threading.Event()
_thread = None
_last = {'started_at': None, 'finished_at': None, 'error': None}


def interval_minutes():
    return int(os.getenv('SCAN_INTERVAL_MINUTES', '30'))


def status():
    return {'running': bool(_thread and _thread.is_alive()),
            'interval_minutes': interval_minutes(), 'last': _last}


def _loop():
    from .core import now
    from .discovery_plus import scan_all
    interval = interval_minutes() * 60
    # Wait first, so a server restart does not immediately hammer every source.
    _stop.wait(interval)
    while not _stop.is_set():
        _last['started_at'] = now()
        try:
            scan_all(trigger='scheduler')
            _last['error'] = None
        except Exception as e:
            _last['error'] = str(e)
        _last['finished_at'] = now()
        _stop.wait(interval)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name='career-agent-scanner')
    _thread.start()


def stop():
    _stop.set()
