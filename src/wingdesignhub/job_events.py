"""Small append-only worker telemetry; calculations do not depend on the UI."""
import json
import os
import threading
import time
from pathlib import Path

_WRITE_LOCK = threading.Lock()


def event(kind, **data):
    directory = os.environ.get('WDH_JOB_DIRECTORY')
    if not directory:
        return
    # Separate processes own separate files. XFOIL workers within one process
    # still need a lock: Windows append handles can overwrite concurrent writes.
    path = Path(directory)/f'events-{os.getpid()}.jsonl'
    with _WRITE_LOCK:
        row = {'time':time.time(),'event':kind,**data}
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
        if kind in ('iteration_completed','aero_point') or (kind=='run' and data.get('progress')):
            from .jobs import atomic
            atomic(Path(directory)/f'progress-{kind}-{os.getpid()}.json',row)


def latest(directory):
    rows = []
    for path in Path(directory).glob('events-*.jsonl'):
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-8192))
            for line in stream.read().splitlines():
                try:rows.append(json.loads(line))
                except (ValueError,UnicodeDecodeError):pass  # unfinished last line / leading fragment
    progress=[json.loads(p.read_text('utf-8')) for p in Path(directory).glob('progress-*.json')]
    return sorted(sorted(rows,key=lambda x:x['time'])[-20:]+progress,key=lambda x:x['time'])
