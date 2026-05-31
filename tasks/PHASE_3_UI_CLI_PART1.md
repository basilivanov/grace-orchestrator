# Phase 3: UI & CLI

**Длительность:** 1 неделя + 2 дня (9 дней)
**Цель:** Создать UI, CLI, notifications

---

## Task #19: Implement JSON-first Artifact Storage

**Приоритет:** Высокий
**Время:** 1 день
**Зависимости:** Task #12

### Описание
Реализовать JSON-first artifact storage structure.

### Что делать

#### 1. Создать artifact storage structure

**src/grace_control/core/artifacts.py:**
```python
"""
Artifact storage management.
"""
from pathlib import Path
from typing import Optional
import json
from datetime import datetime

class ArtifactStorage:
    """
    Manage artifact storage.
    
    Structure:
    .grace/packets/{packet_id}/runs/{run_id}/
    ├── packet.json          # Packet spec
    ├── result.json          # Execution result
    ├── agent/
    │   └── output.json      # Agent output
    ├── tests/
    │   ├── T0.json
    │   ├── T1.json
    │   └── T2.json
    ├── logs.jsonl           # Structured logs
    ├── evidence/
    │   ├── before.png
    │   ├── after.png
    │   └── diff.png
    └── screenshots/
        ├── step1.png
        └── step2.png
    """
    
    def __init__(self, base_path: Path = Path(".grace")):
        self.base_path = base_path
    
    def get_run_path(self, packet_id: str, run_id: str) -> Path:
        """Get path for packet run."""
        return self.base_path / "packets" / packet_id / "runs" / run_id
    
    def create_run_directory(self, packet_id: str, run_id: str):
        """Create directory structure for run."""
        run_path = self.get_run_path(packet_id, run_id)
        run_path.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (run_path / "agent").mkdir(exist_ok=True)
        (run_path / "tests").mkdir(exist_ok=True)
        (run_path / "evidence").mkdir(exist_ok=True)
        (run_path / "screenshots").mkdir(exist_ok=True)
    
    def save_packet_spec(self, packet_id: str, run_id: str, spec: dict):
        """Save packet spec."""
        run_path = self.get_run_path(packet_id, run_id)
        with open(run_path / "packet.json", "w") as f:
            json.dump(spec, f, indent=2)
    
    def save_result(self, packet_id: str, run_id: str, result: dict):
        """Save execution result."""
        run_path = self.get_run_path(packet_id, run_id)
        with open(run_path / "result.json", "w") as f:
            json.dump(result, f, indent=2)
    
    def save_test_result(self, packet_id: str, run_id: str, tier: str, result: dict):
        """Save test result."""
        run_path = self.get_run_path(packet_id, run_id)
        with open(run_path / "tests" / f"{tier}.json", "w") as f:
            json.dump(result, f, indent=2)
    
    def save_agent_output(self, packet_id: str, run_id: str, output: dict):
        """Save agent output."""
        run_path = self.get_run_path(packet_id, run_id)
        with open(run_path / "agent" / "output.json", "w") as f:
            json.dump(output, f, indent=2)
    
    def append_log(self, packet_id: str, run_id: str, log_entry: dict):
        """Append log entry."""
        run_path = self.get_run_path(packet_id, run_id)
        with open(run_path / "logs.jsonl", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    
    def save_screenshot(self, packet_id: str, run_id: str, name: str, data: bytes):
        """Save screenshot."""
        run_path = self.get_run_path(packet_id, run_id)
        screenshot_path = run_path / "screenshots" / name
        screenshot_path.write_bytes(data)
    
    def save_evidence(self, packet_id: str, run_id: str, name: str, data: bytes):
        """Save evidence file."""
        run_path = self.get_run_path(packet_id, run_id)
        evidence_path = run_path / "evidence" / name
        evidence_path.write_bytes(data)
    
    def load_result(self, packet_id: str, run_id: str) -> Optional[dict]:
        """Load execution result."""
        run_path = self.get_run_path(packet_id, run_id)
        result_file = run_path / "result.json"
        
        if not result_file.exists():
            return None
        
        with open(result_file) as f:
            return json.load(f)
    
    def list_runs(self, packet_id: str) -> list[str]:
        """List all runs for packet."""
        packet_path = self.base_path / "packets" / packet_id / "runs"
        if not packet_path.exists():
            return []
        
        return [d.name for d in packet_path.iterdir() if d.is_dir()]
```

#### 2. Интегрировать в worker

**Обновить src/grace_control/worker/worker.py:**
```python
from grace_control.core.artifacts import ArtifactStorage

class Worker:
    def __init__(self, ...):
        # ...
        self.artifacts = ArtifactStorage()
    
    async def _execute_packet(self, claim) -> dict:
        packet_id = claim.packet_id
        run_id = f"R{claim.run_number:02d}"
        
        # Create artifact directory
        self.artifacts.create_run_directory(packet_id, run_id)
        
        # Save packet spec
        self.artifacts.save_packet_spec(packet_id, run_id, claim.spec)
        
        # Execute
        result = await run_e2e_packet(...)
        
        # Save result
        self.artifacts.save_result(packet_id, run_id, result)
        
        # Save test results
        for tier, test_result in result.get("tests", {}).items():
            self.artifacts.save_test_result(packet_id, run_id, tier, test_result)
        
        return result
```

### Критерии готовности
- [ ] ArtifactStorage реализован
- [ ] Directory structure создаётся
- [ ] JSON artifacts сохраняются
- [ ] Screenshots сохраняются
- [ ] Logs сохраняются
- [ ] Интеграция с worker работает

---

## Task #29: Implement Artifact Viewer with Image Support

**Приоритет:** Средний
**Время:** 2 дня
**Зависимости:** Task #19

### Описание
Создать artifact viewer с поддержкой изображений и thumbnails.

### Что делать

#### 1. Добавить artifacts API

**src/grace_control/api/routers/artifacts.py:**
```python
"""
Artifacts API router.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
from PIL import Image
import io

from grace_control.core.artifacts import ArtifactStorage

router = APIRouter()
artifacts = ArtifactStorage()

@router.get("/packets/{packet_id}/runs/{run_id}/result")
async def get_result(packet_id: str, run_id: str):
    """Get execution result."""
    result = artifacts.load_result(packet_id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return result

@router.get("/packets/{packet_id}/runs/{run_id}/tests/{tier}")
async def get_test_result(packet_id: str, run_id: str, tier: str):
    """Get test result."""
    run_path = artifacts.get_run_path(packet_id, run_id)
    test_file = run_path / "tests" / f"{tier}.json"
    
    if not test_file.exists():
        raise HTTPException(status_code=404, detail="Test result not found")
    
    import json
    with open(test_file) as f:
        return json.load(f)

@router.get("/packets/{packet_id}/runs/{run_id}/logs")
async def get_logs(packet_id: str, run_id: str):
    """Get logs."""
    run_path = artifacts.get_run_path(packet_id, run_id)
    logs_file = run_path / "logs.jsonl"
    
    if not logs_file.exists():
        raise HTTPException(status_code=404, detail="Logs not found")
    
    logs = []
    with open(logs_file) as f:
        for line in f:
            logs.append(json.loads(line))
    
    return logs

@router.get("/packets/{packet_id}/runs/{run_id}/screenshots")
async def list_screenshots(packet_id: str, run_id: str):
    """List screenshots."""
    run_path = artifacts.get_run_path(packet_id, run_id)
    screenshots_dir = run_path / "screenshots"
    
    if not screenshots_dir.exists():
        return []
    
    return [
        {
            "name": f.name,
            "size": f.stat().st_size,
            "url": f"/api/artifacts/packets/{packet_id}/runs/{run_id}/screenshots/{f.name}"
        }
        for f in screenshots_dir.iterdir()
        if f.is_file()
    ]

@router.get("/packets/{packet_id}/runs/{run_id}/screenshots/{filename}")
async def get_screenshot(
    packet_id: str,
    run_id: str,
    filename: str,
    thumbnail: bool = False
):
    """Get screenshot (with optional thumbnail)."""
    run_path = artifacts.get_run_path(packet_id, run_id)
    screenshot_path = run_path / "screenshots" / filename
    
    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    
    if thumbnail:
        # Generate thumbnail
        img = Image.open(screenshot_path)
        img.thumbnail((200, 200))
        
        # Return as bytes
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        return StreamingResponse(buf, media_type="image/png")
    else:
        # Return full image
        return FileResponse(screenshot_path)

@router.get("/packets/{packet_id}/runs/{run_id}/evidence/{filename}")
async def get_evidence(packet_id: str, run_id: str, filename: str):
    """Get evidence file."""
    run_path = artifacts.get_run_path(packet_id, run_id)
    evidence_path = run_path / "evidence" / filename
    
    if not evidence_path.exists():
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    return FileResponse(evidence_path)
```

#### 2. Создать frontend components (для HTML dashboard)

**Будет использоваться в Task #30 (HTML Dashboard)**

### Критерии готовности
- [ ] Artifacts API endpoints работают
- [ ] Thumbnail generation работает
- [ ] Image serving работает
- [ ] JSON artifacts возвращаются
- [ ] Logs возвращаются

---

## Task #30: Create Simple HTML Dashboard UI

**Приоритет:** Высокий
**Время:** 2 дня
**Зависимости:** Task #29

### Описание
Создать single-page HTML dashboard с Tailwind CSS.

### Что делать

#### 1. Создать HTML dashboard

**static/grace-ui.html:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GRACE Control Plane</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100">
    <div id="app" class="container mx-auto p-4">
        <!-- Navigation -->
        <nav class="bg-white shadow-md rounded-lg p-4 mb-4">
            <div class="flex space-x-4">
                <button onclick="showPage('features')" class="px-4 py-2 bg-blue-500 text-white rounded">Features</button>
                <button onclick="showPage('packets')" class="px-4 py-2 bg-gray-200 rounded">Packets</button>
                <button onclick="showPage('workers')" class="px-4 py-2 bg-gray-200 rounded">Workers</button>
            </div>
        </nav>

        <!-- Features Page -->
        <div id="features-page" class="page">
            <h1 class="text-2xl font-bold mb-4">Features</h1>
            <div id="features-list" class="space-y-4"></div>
        </div>

        <!-- Packets Page -->
        <div id="packets-page" class="page hidden">
            <h1 class="text-2xl font-bold mb-4">Packets</h1>
            <div id="packets-list" class="space-y-4"></div>
        </div>

        <!-- Workers Page -->
        <div id="workers-page" class="page hidden">
            <h1 class="text-2xl font-bold mb-4">Workers</h1>
            <div id="workers-list" class="space-y-4"></div>
        </div>

        <!-- Packet Detail Modal -->
        <div id="packet-modal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center">
            <div class="bg-white rounded-lg p-6 max-w-4xl w-full max-h-screen overflow-y-auto">
                <div class="flex justify-between items-center mb-4">
                    <h2 id="packet-modal-title" class="text-xl font-bold"></h2>
                    <button onclick="closePacketModal()" class="text-gray-500 hover:text-gray-700">✕</button>
                </div>
                <div id="packet-modal-content"></div>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = 'http://localhost:8000/api';

        // Page navigation
        function showPage(pageName) {
            document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
            document.getElementById(`${pageName}-page`).classList.remove('hidden');
            
            if (pageName === 'features') loadFeatures();
            if (pageName === 'packets') loadPackets();
            if (pageName === 'workers') loadWorkers();
        }

        // Load features
        async function loadFeatures() {
            const response = await fetch(`${API_BASE}/features/`);
            const features = await response.json();
            
            const html = features.map(f => `
                <div class="bg-white shadow rounded-lg p-4">
                    <div class="flex justify-between items-center">
                        <div>
                            <h3 class="text-lg font-semibold">${f.id}</h3>
                            <p class="text-gray-600">${f.title}</p>
                        </div>
                        <span class="px-3 py-1 rounded ${getStatusColor(f.status)}">${f.status}</span>
                    </div>
                </div>
            `).join('');
            
            document.getElementById('features-list').innerHTML = html;
        }

        // Load packets
        async function loadPackets() {
            const response = await fetch(`${API_BASE}/packets/`);
            const packets = await response.json();
            
            const html = packets.map(p => `
                <div class="bg-white shadow rounded-lg p-4 cursor-pointer hover:shadow-lg" onclick="showPacketDetail('${p.id}')">
                    <div class="flex justify-between items-center">
                        <div>
                            <h3 class="text-lg font-semibold">${p.id}</h3>
                            <p class="text-gray-600">${p.title}</p>
                            <p class="text-sm text-gray-500">Profile: ${p.acceptance_profile} | Attempts: ${p.attempt_count}</p>
                        </div>
                        <span class="px-3 py-1 rounded ${getStatusColor(p.state)}">${p.state}</span>
                    </div>
                </div>
            `).join('');
            
            document.getElementById('packets-list').innerHTML = html;
        }

        // Load workers
        async function loadWorkers() {
            const response = await fetch(`${API_BASE}/workers/`);
            const workers = await response.json();
            
            const html = workers.map(w => `
                <div class="bg-white shadow rounded-lg p-4">
                    <div class="flex justify-between items-center">
                        <div>
                            <h3 class="text-lg font-semibold">${w.id}</h3>
                            <p class="text-gray-600">Current: ${w.current_packet_id || 'idle'}</p>
                            <p class="text-sm text-gray-500">Last heartbeat: ${new Date(w.last_heartbeat).toLocaleString()}</p>
                        </div>
                        <span class="px-3 py-1 rounded ${getStatusColor(w.status)}">${w.status}</span>
                    </div>
                </div>
            `).join('');
            
            document.getElementById('workers-list').innerHTML = html;
        }

        // Show packet detail
        async function showPacketDetail(packetId) {
            document.getElementById('packet-modal').classList.remove('hidden');
            document.getElementById('packet-modal-title').textContent = packetId;
            
            // Load packet details
            const response = await fetch(`${API_BASE}/packets/${packetId}`);
            const packet = await response.json();
            
            // Load runs
            // TODO: Implement runs list
            
            const html = `
                <div class="space-y-4">
                    <div>
                        <h3 class="font-semibold">Title</h3>
                        <p>${packet.title}</p>
                    </div>
                    <div>
                        <h3 class="font-semibold">State</h3>
                        <p>${packet.state}</p>
                    </div>
                    <div>
                        <h3 class="font-semibold">Acceptance Profile</h3>
                        <p>${packet.acceptance_profile}</p>
                    </div>
                </div>
            `;
            
            document.getElementById('packet-modal-content').innerHTML = html;
        }

        function closePacketModal() {
            document.getElementById('packet-modal').classList.add('hidden');
        }

        function getStatusColor(status) {
            const colors = {
                'NOT_STARTED': 'bg-gray-200 text-gray-800',
                'IN_PROGRESS': 'bg-blue-200 text-blue-800',
                'COMPLETED': 'bg-green-200 text-green-800',
                'FAILED': 'bg-red-200 text-red-800',
                'draft': 'bg-gray-200 text-gray-800',
                'ready': 'bg-yellow-200 text-yellow-800',
                'running': 'bg-blue-200 text-blue-800',
                'testing': 'bg-purple-200 text-purple-800',
                'accepted': 'bg-green-200 text-green-800',
                'rejected': 'bg-red-200 text-red-800',
                'merged': 'bg-green-300 text-green-900',
                'active': 'bg-green-200 text-green-800',
                'idle': 'bg-gray-200 text-gray-800',
                'dead': 'bg-red-200 text-red-800',
            };
            return colors[status] || 'bg-gray-200 text-gray-800';
        }

        // Auto-refresh every 5 seconds
        setInterval(() => {
            const activePage = document.querySelector('.page:not(.hidden)').id.replace('-page', '');
            showPage(activePage);
        }, 5000);

        // Initial load
        loadFeatures();
    </script>
</body>
</html>
```

#### 2. Serve static files

**Обновить src/grace_control/api/main.py:**
```python
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/grace-ui.html")
```

### Критерии готовности
- [ ] HTML dashboard создан
- [ ] Features list работает
- [ ] Packets list работает
- [ ] Workers list работает
- [ ] Packet detail modal работает
- [ ] Auto-refresh работает
- [ ] Responsive design

---

Продолжить с остальными задачами Phase 3 (CLI, Telegram, grace init)?
