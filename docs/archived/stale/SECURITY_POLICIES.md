# Security Policies

## Overview

GRACE Orchestrator implements security policies to protect against accidental or unauthorized access to sensitive resources. This document describes the dangerous sandbox bypass policy gate and its audit logging.

## Dangerous Sandbox Bypass

### What is Dangerous Sandbox Bypass?

The `danger-full-access` sandbox mode combined with `approval=never` grants the Codex agent:
- Full filesystem access without restrictions
- No approval prompts for dangerous operations
- Ability to read/write/delete any file the orchestrator process can access

This mode is intended for:
- Development and testing environments
- Trusted automation workflows
- Situations where full access is explicitly required

**WARNING:** Never use `danger-full-access` in production environments or with untrusted code.

## Policy Gate

### How Approval Works

All attempts to use dangerous sandbox bypass are gated by a policy check. The policy follows this precedence (highest to lowest):

1. **Environment Variable** (highest priority)
   - `GRACE_ALLOW_SANDBOX_BYPASS=true` - Allows bypass
   - `GRACE_ALLOW_SANDBOX_BYPASS=1` - Allows bypass
   - `GRACE_ALLOW_SANDBOX_BYPASS=yes` - Allows bypass
   - Any other value or unset - Denies bypass

2. **Project Configuration**
   - `security.allow_sandbox_bypass: true` in `project.yaml` - Allows bypass
   - `security.allow_sandbox_bypass: false` or unset - Denies bypass

3. **Default: DENY**
   - If neither environment variable nor config allows, bypass is denied

### Policy Decision Flow

```
┌─────────────────────────────────────┐
│ Packet requests danger-full-access  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Check GRACE_ALLOW_SANDBOX_BYPASS    │
│ environment variable                │
└──────────────┬──────────────────────┘
               │
               ├─ true/1/yes ──────────┐
               │                       │
               ├─ false/other ─────────┤
               │                       │
               ▼                       │
┌─────────────────────────────────────┐│
│ Check project.yaml                  ││
│ security.allow_sandbox_bypass       ││
└──────────────┬──────────────────────┘│
               │                       │
               ├─ true ────────────────┤
               │                       │
               ├─ false/unset ─────────┤
               │                       │
               ▼                       ▼
         ┌─────────┐           ┌─────────┐
         │  DENY   │           │  ALLOW  │
         └─────────┘           └─────────┘
              │                       │
              ▼                       ▼
    ┌──────────────────┐    ┌──────────────────┐
    │ Raise exception  │    │ Add bypass flag  │
    │ Log denied       │    │ Log allowed      │
    └──────────────────┘    └──────────────────┘
```

## Audit Logging

### Purpose

All sandbox bypass attempts (allowed and denied) are logged to a JSONL audit file for:
- Security compliance and review
- Incident investigation
- Usage tracking and analysis

### Log Format

Each audit entry is a JSON object on a single line:

```json
{
  "timestamp": "2026-05-30T14:23:45.123456Z",
  "packet_id": "FEAT-AUTH-V1",
  "allowed": true,
  "reason": "sandbox=danger-full-access, approval=never",
  "policy_reason": "Allowed by GRACE_ALLOW_SANDBOX_BYPASS environment variable",
  "hostname": "grace-worker-01",
  "user": "grace-service"
}
```

### Log Location

Default: `/var/lib/grace-orchestrator/audit/sandbox_bypass.jsonl`

Override in `project.yaml`:
```yaml
security:
  sandbox_bypass_audit_log: "/custom/path/audit.jsonl"
```

### Log Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 timestamp in UTC |
| `packet_id` | string | Packet identifier |
| `allowed` | boolean | Whether bypass was allowed |
| `reason` | string | Why bypass was requested |
| `policy_reason` | string | Policy decision explanation |
| `hostname` | string | Hostname of the orchestrator |
| `user` | string | OS user running the orchestrator |

### Graceful Degradation

Audit logging failures do not fail operations. If the audit log cannot be written:
- A warning is logged to the application log
- The operation continues normally
- This prevents audit log issues from blocking legitimate work

## Usage Examples

### Allow Temporarily (Environment Variable)

For a single session or deployment:

```bash
export GRACE_ALLOW_SANDBOX_BYPASS=true
grace-orchestrator run FEAT-AUTH-V1
```

### Allow Permanently (Project Config)

In `project.yaml`:

```yaml
security:
  allow_sandbox_bypass: true
  sandbox_bypass_audit_log: "/var/lib/grace-orchestrator/audit/sandbox_bypass.jsonl"
```

### Denied Example

Without approval, attempts will fail:

```
SandboxBypassDenied: Sandbox bypass denied: Sandbox bypass not allowed. 
Set GRACE_ALLOW_SANDBOX_BYPASS=true environment variable or add 
'security.allow_sandbox_bypass: true' to project.yaml
```

The denial is also logged to the audit file:

```json
{
  "timestamp": "2026-05-30T14:30:00.000000Z",
  "packet_id": "FEAT-AUTH-V1",
  "allowed": false,
  "reason": "sandbox=danger-full-access, approval=never",
  "policy_reason": "Sandbox bypass not allowed. Set GRACE_ALLOW_SANDBOX_BYPASS=true...",
  "hostname": "grace-worker-01",
  "user": "grace-service"
}
```

## Best Practices

### Development

✅ **DO:**
- Use environment variable for temporary testing
- Review audit logs regularly
- Use `danger-full-access` only when necessary
- Document why bypass is needed in packet metadata

❌ **DON'T:**
- Enable bypass in production environments
- Commit `allow_sandbox_bypass: true` to version control for production configs
- Ignore audit log warnings
- Use bypass as default for all packets

### Production

✅ **DO:**
- Use restrictive sandbox modes (`workspace-write`, `workspace-read`)
- Monitor audit logs for unexpected bypass attempts
- Require approval for sensitive operations
- Implement least-privilege access

❌ **DON'T:**
- Enable `allow_sandbox_bypass` in production
- Disable audit logging
- Grant bypass access without review
- Use `approval=never` for production workflows

### Audit Review

Regularly review audit logs for:
- Unexpected bypass attempts (denied entries)
- Unusual patterns or frequency
- Bypass usage in production environments
- Unauthorized users attempting bypass

Example audit log query:
```bash
# Show all denied attempts
jq 'select(.allowed == false)' /var/lib/grace-orchestrator/audit/sandbox_bypass.jsonl

# Show attempts by packet
jq 'select(.packet_id == "FEAT-AUTH-V1")' /var/lib/grace-orchestrator/audit/sandbox_bypass.jsonl

# Count attempts per day
jq -r '.timestamp[:10]' /var/lib/grace-orchestrator/audit/sandbox_bypass.jsonl | sort | uniq -c
```

## Migration

### Before (Unconditional Bypass)

```python
# Old behavior: bypass always added when conditions met
if sandbox == "danger-full-access" and approval == "never":
    command.append("--dangerously-bypass-approvals-and-sandbox")
```

### After (Policy-Gated Bypass)

```python
# New behavior: policy check required
if _uses_bypass_sandbox(sandbox, approval, packet_id, project_config):
    # Policy check passed, audit logged
    command.append("--dangerously-bypass-approvals-and-sandbox")
else:
    # Normal sandbox mode
    command.extend(["--sandbox", sandbox])
```

### Updating Existing Deployments

1. **Review current usage:**
   ```bash
   # Find packets using danger-full-access
   grep -r "danger-full-access" grace/packets/
   ```

2. **Choose approval method:**
   - Temporary: Set `GRACE_ALLOW_SANDBOX_BYPASS=true` environment variable
   - Permanent: Add `security.allow_sandbox_bypass: true` to `project.yaml`

3. **Test the change:**
   ```bash
   # Verify policy allows bypass
   grace-orchestrator run FEAT-TEST-V1 --dry-run
   ```

4. **Monitor audit logs:**
   ```bash
   tail -f /var/lib/grace-orchestrator/audit/sandbox_bypass.jsonl
   ```

## Troubleshooting

### Error: "Sandbox bypass denied"

**Cause:** Policy gate is blocking dangerous sandbox bypass.

**Solution:**
1. Verify the packet actually needs `danger-full-access`
2. Set `GRACE_ALLOW_SANDBOX_BYPASS=true` environment variable, OR
3. Add `security.allow_sandbox_bypass: true` to `project.yaml`

### Audit log not created

**Cause:** Permission issues or invalid path.

**Solution:**
1. Check directory permissions: `ls -ld /var/lib/grace-orchestrator/audit/`
2. Create directory: `mkdir -p /var/lib/grace-orchestrator/audit/`
3. Check application logs for warnings

### Environment variable not working

**Cause:** Variable not set in orchestrator process environment.

**Solution:**
1. Verify variable is set: `echo $GRACE_ALLOW_SANDBOX_BYPASS`
2. Export variable: `export GRACE_ALLOW_SANDBOX_BYPASS=true`
3. For systemd services, add to service file:
   ```ini
   [Service]
   Environment="GRACE_ALLOW_SANDBOX_BYPASS=true"
   ```

## Security Considerations

### Threat Model

The policy gate protects against:
- **Accidental bypass:** Developer forgets to remove `danger-full-access` from packet
- **Configuration drift:** Production config accidentally includes bypass
- **Unauthorized access:** Malicious packet attempts full filesystem access

The policy gate does NOT protect against:
- **Compromised orchestrator:** Attacker with orchestrator access can set environment variable
- **Malicious admin:** User with config write access can enable bypass
- **Process privilege escalation:** Bypass only grants access within orchestrator process privileges

### Defense in Depth

This policy is one layer of defense. Additional protections:
- Run orchestrator with minimal OS privileges
- Use container/VM isolation for orchestrator
- Implement network segmentation
- Monitor and alert on audit log events
- Regular security reviews of packet configurations

## References

- [Codex CLI Sandbox Documentation](https://docs.anthropic.com/codex/sandbox)
- [GRACE Packet Specification](./PACKET_SPEC.md)
- [Project Configuration Guide](./PROJECT_CONFIG.md)
