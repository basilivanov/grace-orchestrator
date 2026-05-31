# Phase 3: UI & CLI - Part 2

## Task #20: Create Thin CLI Wrapper over API

**Приоритет:** Средний
**Время:** 1 день
**Зависимости:** Task #18

### Описание
Создать CLI wrapper над API с JSON output для агентов.

### Что делать

#### 1. Создать CLI app

**src/grace_control/cli/main.py:**
```python
"""
CLI wrapper for GRACE Control Plane.
"""
import click
import httpx
import json
from rich.console import Console
from rich.table import Table

console = Console()
API_BASE = "http://localhost:8000/api"

@click.group()
def cli():
    """GRACE Control Plane CLI"""
    pass

@cli.group()
def packet():
    """Packet commands"""
    pass

@packet.command()
@click.option('--state', help='Filter by state')
@click.option('--json', 'json_output', is_flag=True, help='JSON output')
def list(state, json_output):
    """List packets"""
    url = f"{API_BASE}/packets/"
    if state:
        url += f"?state={state}"
    
    response = httpx.get(url)
    packets = response.json()
    
    if json_output:
        click.echo(json.dumps(packets, indent=2))
    else:
        table = Table(title="Packets")
        table.add_column("ID")
        table.add_column("Title")
        table.add_column("State")
        table.add_column("Profile")
        
        for p in packets:
            table.add_row(p['id'], p['title'], p['state'], p['acceptance_profile'])
        
        console.print(table)

@packet.command()
@click.argument('packet_id')
@click.option('--json', 'json_output', is_flag=True)
def get(packet_id, json_output):
    """Get packet details"""
    response = httpx.get(f"{API_BASE}/packets/{packet_id}")
    packet = response.json()
    
    if json_output:
        click.echo(json.dumps(packet, indent=2))
    else:
        console.print(f"[bold]{packet['id']}[/bold]")
        console.print(f"Title: {packet['title']}")
        console.print(f"State: {packet['state']}")
        console.print(f"Profile: {packet['acceptance_profile']}")

@packet.command()
@click.argument('packet_id')
@click.option('--reason', help='Cancellation reason')
def cancel(packet_id, reason):
    """Cancel packet"""
    response = httpx.post(f"{API_BASE}/packets/{packet_id}/cancel", json={
        "reason": reason
    })
    
    if response.status_code == 200:
        console.print(f"[green]Packet {packet_id} cancelled[/green]")
    else:
        console.print(f"[red]Error: {response.text}[/red]")

if __name__ == '__main__':
    cli()
```

### Критерии готовности
- [ ] CLI app создан
- [ ] Packet commands работают
- [ ] JSON output работает
- [ ] Rich formatting работает

---

## Task #25: Implement Telegram Bot Notifications

**Приоритет:** Средний
**Время:** 1 день
**Зависимости:** Task #18

### Описание
Создать Telegram bot для уведомлений.

### Что делать

#### 1. Создать Telegram notifier

**src/grace_control/notifications/telegram.py:**
```python
"""
Telegram notifications.
"""
from telegram import Bot
import os
from grace_control.logging import GraceLogger

logger = GraceLogger("telegram")

class TelegramNotifier:
    """Send notifications via Telegram."""
    
    def __init__(self):
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not token or not chat_id:
            logger.warning("Telegram not configured")
            self.enabled = False
            return
        
        self.bot = Bot(token=token)
        self.chat_id = chat_id
        self.enabled = True
    
    async def send(self, message: str):
        """Send message."""
        if not self.enabled:
            return
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error("Failed to send Telegram message", error=str(e))
    
    async def notify_packet_accepted(self, packet_id: str, attempt: int):
        """Notify packet accepted."""
        message = f"✅ *Packet Accepted*\n\n`{packet_id}`\nAttempt: {attempt}"
        await self.send(message)
    
    async def notify_packet_rejected(self, packet_id: str, reason: str):
        """Notify packet rejected."""
        message = f"❌ *Packet Rejected*\n\n`{packet_id}`\nReason: {reason}"
        await self.send(message)
    
    async def notify_feature_completed(self, feature_id: str):
        """Notify feature completed."""
        message = f"🎉 *Feature Completed*\n\n`{feature_id}`"
        await self.send(message)
```

### Критерии готовности
- [ ] TelegramNotifier реализован
- [ ] Уведомления отправляются
- [ ] Error handling работает

---

## Task #26: Create grace init Command

**Приоритет:** Средний
**Время:** 1 день
**Зависимости:** Task #20

### Описание
Создать `grace init` для инициализации проекта.

### Что делать

#### 1. Добавить init command

**src/grace_control/cli/commands/init.py:**
```python
"""
Init command.
"""
import click
from pathlib import Path
import yaml

@click.command()
@click.option('--project-key', prompt='Project key', help='Project key (e.g., my-app)')
@click.option('--project-name', prompt='Project name', help='Project name')
def init(project_key, project_name):
    """Initialize GRACE project"""
    
    # Create grace/ directory
    grace_dir = Path("grace")
    grace_dir.mkdir(exist_ok=True)
    
    # Create project.yaml
    project_config = {
        "project": {
            "key": project_key,
            "name": project_name,
        },
        "logging": {
            "level": "INFO",
            "components": {
                "worker": "DEBUG",
                "executor": "INFO",
            }
        },
        "testing": {
            "parallel": True,
            "max_workers": 4,
        }
    }
    
    with open(grace_dir / "project.yaml", "w") as f:
        yaml.dump(project_config, f, default_flow_style=False)
    
    # Create XML artifacts directory
    (grace_dir / "artifacts").mkdir(exist_ok=True)
    
    click.echo(f"✅ Initialized GRACE project: {project_name}")
    click.echo(f"   Project key: {project_key}")
    click.echo(f"   Config: grace/project.yaml")
```

### Критерии готовности
- [ ] grace init работает
- [ ] project.yaml создаётся
- [ ] Directories создаются

---

## Task #33: Implement Packet Cancellation

**Приоритет:** Критично
**Время:** 1 день
**Зависимости:** Task #12

### Описание
Реализовать graceful cancellation для packets.

### Что делать

#### 1. Добавить cancellation flag в worker

**Обновить src/grace_control/worker/worker.py:**
```python
class Worker:
    def __init__(self, ...):
        # ...
        self.current_packet_id = None
        self.cancellation_requested = False
    
    async def _execute_packet(self, claim) -> dict:
        self.current_packet_id = claim.packet_id
        self.cancellation_requested = False
        
        # Start cancellation check task
        cancel_task = asyncio.create_task(self._check_cancellation())
        
        try:
            # Execute with cancellation support
            result = await self._execute_with_cancellation(claim)
            return result
        finally:
            cancel_task.cancel()
            self.current_packet_id = None
    
    async def _check_cancellation(self):
        """Check for cancellation flag periodically."""
        while True:
            await asyncio.sleep(5)
            
            if not self.current_packet_id:
                break
            
            # Check DB for cancellation
            with get_db() as db:
                packet = db.query(Packet).filter_by(id=self.current_packet_id).first()
                if packet and packet.state == PacketState.CANCELLED:
                    self.cancellation_requested = True
                    logger.warning("Cancellation requested", packet_id=self.current_packet_id)
                    break
    
    async def _execute_with_cancellation(self, claim):
        """Execute with cancellation support."""
        # TODO: Implement cancellation in run_e2e_packet
        pass
```

### Критерии готовности
- [ ] Cancellation flag проверяется
- [ ] Graceful shutdown работает
- [ ] Worktree cleanup работает

---

## Task #34: Implement Health Checks

**Приоритет:** Критично
**Время:** 1 день
**Зависимости:** Task #18

### Описание
Реализовать comprehensive health checks.

### Что делать

#### 1. Расширить health check

**Обновить src/grace_control/core/health.py:**
```python
import shutil
from grace_control.core.executors import create_executor

async def check_health() -> dict:
    """Comprehensive health check."""
    
    # Check workers
    workers_health = await check_workers()
    
    # Check executors
    executors_health = await check_executors()
    
    # Check DB
    db_health = check_db()
    
    # Check disk space
    disk_health = check_disk()
    
    # Overall status
    status = "healthy"
    if any(h["status"] == "degraded" for h in [workers_health, executors_health, db_health, disk_health]):
        status = "degraded"
    if any(h["status"] == "unhealthy" for h in [workers_health, executors_health, db_health, disk_health]):
        status = "unhealthy"
    
    return {
        "status": status,
        "workers": workers_health,
        "executors": executors_health,
        "db": db_health,
        "disk": disk_health,
        "timestamp": datetime.utcnow().isoformat()
    }

async def check_executors() -> dict:
    """Check executor health."""
    # Load executor configs
    # Ping each executor
    # Return status
    pass

def check_disk() -> dict:
    """Check disk space."""
    usage = shutil.disk_usage("/")
    free_gb = usage.free / (1024**3)
    
    status = "healthy"
    if free_gb < 10:
        status = "degraded"
    if free_gb < 5:
        status = "unhealthy"
    
    return {
        "status": status,
        "free_gb": round(free_gb, 2),
        "total_gb": round(usage.total / (1024**3), 2)
    }
```

### Критерии готовности
- [ ] Workers health check работает
- [ ] Executors health check работает
- [ ] DB health check работает
- [ ] Disk health check работает

---

## Phase 3 Complete Checklist

### Все задачи Phase 3
- [ ] Task #19: JSON Artifacts ✅
- [ ] Task #29: Artifact Viewer ✅
- [ ] Task #30: HTML Dashboard ✅
- [ ] Task #20: CLI Wrapper ✅
- [ ] Task #25: Telegram Bot ✅
- [ ] Task #26: grace init ✅
- [ ] Task #33: Cancellation ✅
- [ ] Task #34: Health Checks ✅

### Deliverables
- ✅ JSON artifact storage
- ✅ Artifact viewer с images
- ✅ HTML dashboard
- ✅ CLI wrapper
- ✅ Telegram notifications
- ✅ grace init command
- ✅ Packet cancellation
- ✅ Health checks

### Готовность к Phase 4
После завершения Phase 3 можно начинать Phase 4: Testing & Polish
