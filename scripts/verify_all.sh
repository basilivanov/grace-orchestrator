#!/bin/bash
set -e
cd "$(dirname "$0")/.."
API="http://localhost:8042"
PY=".venv/bin/python"

echo "=== GRACE Control Plane — Full Verification ==="
echo ""

echo "[1/7] Unit Tests"
$PY -m pytest tests/ --asyncio-mode=auto -q
echo ""

echo "[2/7] API Health"
$PY -c "import httpx; r=httpx.get('$API/health',timeout=5); assert r.status_code==200; print('OK:',r.json()['status'])"
echo ""

echo "[3/7] Dashboard"
$PY -c "import httpx; r=httpx.get('$API/',timeout=5); assert 'GRACE' in r.text; print('OK:',len(r.text),'bytes')"
echo ""

echo "[4/7] Architect Plan"
PID=$($PY -c "
import httpx
r=httpx.post('$API/api/architect/plan',json={'feature_spec':{'title':'Verify','waves':[{'title':'W1','packets':[{'title':'P1','scope':'x.py'}]}]}},timeout=5)
assert r.status_code==200
print(r.json()['data']['packets'][0])
")
echo "OK: $PID"
$PY -c "import httpx; r=httpx.get('$API/api/packets/$PID',timeout=5); assert r.json()['data']['state']=='ready'; print('State: ready')"

echo ""
echo "[5/7] Worker Register + Claim"
$PY -c "
import httpx
c=httpx.Client(base_url='$API',timeout=5)
c.post('/api/workers/register',json={'worker_id':'verify'})
r=c.post('/api/packets/claim',json={'worker_id':'verify'})
assert r.status_code==200
d=r.json()['data']
assert d['lease_id'] is not None
print('OK: claimed',d['packet_id'],'lease',d['lease_id'])
r=c.get('/api/packets/$PID')
assert r.json()['data']['state']=='running'
print('State: running')
"
echo ""

echo "[6/7] Release + Merge"
$PY -c "
import httpx
c=httpx.Client(base_url='$API',timeout=5)
r=c.post('/api/packets/$PID/release',json={'worker_id':'verify','status':'accepted','result':{'accepted':True}})
assert r.status_code==200
print('OK: released →',r.json()['data']['state'])
r=c.post('/api/packets/$PID/merge',json={})
assert r.status_code==200
print('OK: merged →',r.json()['data']['state'])
r=c.get('/api/packets/$PID')
assert r.json()['data']['state']=='merged'
print('Final: merged')
"
echo ""

echo "[7/7] Cancel Blocked"
$PY -c "
import httpx
r=httpx.post('$API/api/packets/$PID/cancel',json={'reason':'test'},timeout=5)
assert r.status_code==400
print('OK: cancel blocked (terminal packet)')
"
echo ""

echo "=== ALL 7 STEPS PASSED ==="
