# GRACE Control Plane - API Contract

**Версия:** 1.0 MVP
**Base URL:** `http://localhost:8042/api`

Этот документ — единственный источник правды для всех API endpoints.

---

## Authentication

**MVP:** No authentication (localhost only)

**Post-MVP:** API keys via `Authorization: Bearer <token>`

---

## Common Response Format

### Success Response
```json
{
  "data": { ... },
  "timestamp": "2026-05-31T10:00:00Z"
}
```

### Error Response
```json
{
  "error": {
    "code": "PACKET_NOT_FOUND",
    "message": "Packet PKT-001 not found",
    "details": {}
  },
  "timestamp": "2026-05-31T10:00:00Z"
}
```

---

## Features API

### List Features

```
GET /api/features/
```

**Response:**
```json
{
  "data": [
    {
      "id": "FEAT-USER-AUTH",
      "slug": "user-auth",
      "title": "User Authentication",
      "description": "Add JWT-based authentication",
      "status": "IN_PROGRESS",
      "created_at": "2026-05-31T10:00:00Z",
      "updated_at": "2026-05-31T10:05:00Z"
    }
  ]
}
```

### Get Feature

```
GET /api/features/{feature_id}
```

**Response:**
```json
{
  "data": {
    "id": "FEAT-USER-AUTH",
    "slug": "user-auth",
    "title": "User Authentication",
    "description": "Add JWT-based authentication",
    "status": "IN_PROGRESS",
    "spec_json": { ... },
    "waves": [
      {
        "id": "W01-FOUNDATION",
        "title": "Foundation",
        "packets_count": 3
      }
    ],
    "created_at": "2026-05-31T10:00:00Z",
    "updated_at": "2026-05-31T10:05:00Z"
  }
}
```

---

## Packets API

### List Packets

```
GET /api/packets/?state=ready&feature_id=FEAT-USER-AUTH
```

**Query Parameters:**
- `state` (optional): Filter by state
- `feature_id` (optional): Filter by feature

**Response:**
```json
{
  "data": [
    {
      "id": "FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS",
      "feature_id": "FEAT-USER-AUTH",
      "wave_id": "W01-FOUNDATION",
      "slug": "add-jwt-utils",
      "title": "Add JWT utilities",
      "state": "ready",
      "acceptance_profile": "NORMAL",
      "attempt_count": 0,
      "max_attempts": 3,
      "created_at": "2026-05-31T10:00:00Z",
      "updated_at": "2026-05-31T10:00:00Z"
    }
  ]
}
```

### Get Packet

```
GET /api/packets/{packet_id}
```

**Response:**
```json
{
  "data": {
    "id": "FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS",
    "feature_id": "FEAT-USER-AUTH",
    "wave_id": "W01-FOUNDATION",
    "slug": "add-jwt-utils",
    "title": "Add JWT utilities",
    "description": "Create JWT encode/decode utilities",
    "state": "accepted",
    "acceptance_profile": "NORMAL",
    "attempt_count": 1,
    "max_attempts": 3,
    "spec_json": {
      "scope": "src/auth/jwt.py",
      "requirements": "..."
    },
    "runs": [
      {
        "id": "R01",
        "run_number": 1,
        "status": "accepted",
        "evidence_path": ".grace/packets/FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS/runs/R01",
        "started_at": "2026-05-31T10:01:00Z",
        "finished_at": "2026-05-31T10:05:00Z",
        "duration_ms": 240000
      }
    ],
    "created_at": "2026-05-31T10:00:00Z",
    "updated_at": "2026-05-31T10:05:00Z"
  }
}
```

### Cancel Packet (Post-MVP)

```
POST /api/packets/{packet_id}/cancel
```

**Request:**
```json
{
  "reason": "No longer needed"
}
```

**Response:**
```json
{
  "data": {
    "packet_id": "FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS",
    "state": "cancelled",
    "reason": "No longer needed"
  }
}
```

---

## Workers API

### List Workers

```
GET /api/workers/
```

**Response:**
```json
{
  "data": [
    {
      "id": "worker-abc123",
      "status": "active",
      "current_packet_id": "FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS",
      "last_heartbeat": "2026-05-31T10:05:00Z",
      "started_at": "2026-05-31T10:00:00Z"
    }
  ]
}
```

### Register Worker

```
POST /api/workers/register
```

**Request:**
```json
{
  "worker_id": "worker-abc123"
}
```

**Response:**
```json
{
  "data": {
    "worker_id": "worker-abc123",
    "status": "registered"
  }
}
```

### Worker Heartbeat

```
POST /api/workers/heartbeat
```

**Request:**
```json
{
  "worker_id": "worker-abc123"
}
```

**Response:**
```json
{
  "data": {
    "worker_id": "worker-abc123",
    "status": "ok",
    "timestamp": "2026-05-31T10:05:00Z"
  }
}
```

---

## Worker Operations (Internal)

### Claim Packet

```
POST /api/packets/claim
```

**Request:**
```json
{
  "worker_id": "worker-abc123"
}
```

**Response (Success):**
```json
{
  "data": {
    "packet_id": "FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS",
    "spec": {
      "scope": "src/auth/jwt.py",
      "requirements": "..."
    },
    "lease_id": 123,
    "expires_at": "2026-05-31T10:35:00Z"
  }
}
```

**Response (No packets available):**
```json
{
  "error": {
    "code": "NO_PACKETS_AVAILABLE",
    "message": "No packets available to claim"
  }
}
```

### Release Packet

```
POST /api/packets/{packet_id}/release
```

**Request:**
```json
{
  "worker_id": "worker-abc123",
  "status": "accepted",
  "result": {
    "accepted": true,
    "reason": null,
    "evidence_path": ".grace/packets/.../runs/R01",
    "duration_ms": 240000,
    "tests": {
      "T0": {"passed": true},
      "T1": {"passed": true}
    }
  }
}
```

**Response:**
```json
{
  "data": {
    "packet_id": "FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS",
    "state": "accepted",
    "released": true
  }
}
```

---

## Architect API

### Create Plan

```
POST /api/architect/plan
```

**Request:**
```json
{
  "feature_spec": {
    "title": "User Authentication",
    "description": "Add JWT-based authentication",
    "waves": [
      {
        "title": "Foundation",
        "packets": [
          {
            "title": "Add JWT utilities",
            "scope": "src/auth/jwt.py",
            "acceptance_profile": "NORMAL"
          }
        ]
      }
    ]
  }
}
```

**Response:**
```json
{
  "data": {
    "feature_id": "FEAT-USER-AUTH",
    "waves_count": 1,
    "packets_count": 1,
    "packets": [
      "FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS"
    ]
  }
}
```

---

## System API

### Health Check

```
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "workers": {
    "active": 1,
    "idle": 0,
    "dead": 0
  },
  "queue_depth": 3,
  "running": 1,
  "timestamp": "2026-05-31T10:05:00Z"
}
```

**Status values:**
- `healthy` — all systems operational
- `degraded` — some workers dead or queue backing up
- `unhealthy` — no active workers or critical failure

---

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `PACKET_NOT_FOUND` | 404 | Packet ID not found |
| `FEATURE_NOT_FOUND` | 404 | Feature ID not found |
| `WORKER_NOT_FOUND` | 404 | Worker ID not found |
| `NO_PACKETS_AVAILABLE` | 404 | No packets in READY state |
| `PACKET_ALREADY_CLAIMED` | 409 | Packet has active lease |
| `INVALID_STATE_TRANSITION` | 400 | Invalid state transition |
| `VALIDATION_ERROR` | 422 | Request validation failed |
| `INTERNAL_ERROR` | 500 | Internal server error |

---

## Rate Limits (Post-MVP)

**MVP:** No rate limits

**Post-MVP:**
- 100 requests/minute per IP
- 1000 requests/hour per API key

---

## Versioning

**MVP:** No versioning (breaking changes allowed)

**Post-MVP:** `/api/v1/...` with semantic versioning

---

## Notes

1. All timestamps are UTC in ISO 8601 format
2. All IDs are strings (hierarchical: `FEAT-X-W01-P01-ACTION`)
3. Pagination not in MVP (will be added post-MVP)
4. Filtering limited to `state` and `feature_id` in MVP
5. No bulk operations in MVP
6. No webhooks in MVP
7. No WebSocket in MVP

---

**This is the single source of truth for API contract.**
