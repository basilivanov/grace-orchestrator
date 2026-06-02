import os, sys, asyncio
sys.path.insert(0, 'src')
os.environ['GRACE_ALLOW_SANDBOX_BYPASS'] = 'true'
os.environ.setdefault('GRACE_DB_URL', 'sqlite:////tmp/grace_live.db')
from pathlib import Path
from grace_control.db import init_db
from grace_control.worker.worker import Worker
init_db()
w = Worker(worker_id='eval-w1', api_url='http://127.0.0.1:8042',
           project_root=Path('.'), state_root=Path('.grace_state'),
           worktree_root=Path('.grace_worktrees'))
async def m(): await w.start()
asyncio.run(m())
