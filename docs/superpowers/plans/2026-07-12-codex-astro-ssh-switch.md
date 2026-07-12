# Codex astro SSH Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every Codex process that can mutate `/opt/grace-orchestrator` as `astro:astro` instead of `root:root`.

**Architecture:** Authorize the current Codex Desktop public key for `astro` without removing root recovery access. Reconnect the client as `astro`, verify the resulting process identity and control socket, then stop the obsolete root Codex processes and repair only root-owned workspace paths.

**Tech Stack:** OpenSSH, Linux users and permissions, Codex app-server, Git, Bash, systemd process inspection.

## Global Constraints

- Use the exact current client key fingerprint `SHA256:AeQ921yO2uuSKXqOmBygoZsT3U/1akg4xj8l9wEajXc`.
- The target identity is UID `1001`, GID `1003`, user and group `astro`.
- The target home is `/home/astro`; the target workspace is `/opt/grace-orchestrator`.
- Do not remove or modify root SSH authorization until the astro path is verified.
- Do not modify existing tracked or untracked project work.
- Repair only paths currently owned by root; do not run an unconditional recursive `chown`.
- Run `python3 scripts/grace_lint.py` before declaring completion.

---

# ############################################################################
# AI_HEADER: codex_astro_ssh_switch_plan - executable plan for changing the Codex SSH identity
# ROLE: Defines the exact preparation, cutover, cleanup, rollback, and verification commands for the host-level identity change.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Move Codex workspace mutation from root to astro while preserving a verified rollback path.
# inputs: Current root authorized_keys, astro account, active Codex connection, and grace-orchestrator workspace.
# returns: An astro-owned Codex process tree and workspace with no root-owned paths.
# side_effects: Creates astro authorized_keys, reconnects Codex, stops obsolete root Codex processes, and changes ownership of root-owned workspace paths.
# emitted_logs: none.
# error_behavior: Stops before destructive cleanup when any authentication or identity check fails.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - task: Prepare astro SSH authorization
#   - task: Cut over the Codex connection
#   - task: Clean up and verify ownership
# END_MODULE_MAP

### Task 1: Prepare astro SSH authorization

**Files:**
- Create: `/home/astro/.ssh/authorized_keys`
- Preserve: `/root/.ssh/authorized_keys`
- Verify: `/etc/ssh/sshd_config` effective settings through `sshd -T`

**Interfaces:**
- Consumes: The third key in `/root/.ssh/authorized_keys`, verified by its exact fingerprint.
- Produces: A mode `0600`, `astro:astro` authorized key file accepted by SSHD.

- [ ] **Step 1: Assert that astro does not already have an authorization file**

Run:

```bash
test ! -e /home/astro/.ssh/authorized_keys
```

Expected: exit code `0`. If it fails, inspect and merge explicitly instead of overwriting.

- [ ] **Step 2: Verify the selected source key before copying it**

Run:

```bash
sed -n '3p' /root/.ssh/authorized_keys >/tmp/codex-astro-authorized-key
ssh-keygen -lf /tmp/codex-astro-authorized-key
```

Expected output contains exactly:

```text
SHA256:AeQ921yO2uuSKXqOmBygoZsT3U/1akg4xj8l9wEajXc
```

- [ ] **Step 3: Install the key with the target identity and permissions**

Run:

```bash
install -d -m 0700 -o astro -g astro /home/astro/.ssh
install -m 0600 -o astro -g astro /tmp/codex-astro-authorized-key /home/astro/.ssh/authorized_keys
rm -f /tmp/codex-astro-authorized-key
```

Expected: `/home/astro/.ssh/authorized_keys` is `astro:astro` mode `600`.

- [ ] **Step 4: Verify the installed key and effective SSHD policy**

Run:

```bash
ssh-keygen -lf /home/astro/.ssh/authorized_keys
stat -c '%U:%G %a %n' /home/astro/.ssh /home/astro/.ssh/authorized_keys
sshd -T -C user=astro,host=bivanov.fvds.ru,addr=5.139.227.10 | rg '^(pubkeyauthentication|authorizedkeysfile|allowtcpforwarding)'
```

Expected:

```text
SHA256:AeQ921yO2uuSKXqOmBygoZsT3U/1akg4xj8l9wEajXc
astro:astro 700 /home/astro/.ssh
astro:astro 600 /home/astro/.ssh/authorized_keys
pubkeyauthentication yes
authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2
allowtcpforwarding yes
```

### Task 2: Cut over the Codex connection

**Files:**
- Read: `/home/astro/.codex-api/app-server-control/app-server-control.sock`
- Preserve until verification: `/root/.codex-api/app-server-control/app-server-control.sock`

**Interfaces:**
- Consumes: The verified astro SSH authorization from Task 1.
- Produces: A Codex app-server and proxy process tree owned by astro.

- [ ] **Step 1: Change the Codex Desktop SSH username and reconnect**

Set the connection username from `root` to `astro` while keeping the same host
and private key. Do not terminate the current root app-server yet.

Expected: Codex Desktop establishes a new task connection without an SSH
authentication error.

- [ ] **Step 2: Verify the new executor identity before any workspace write**

Run in the new Codex connection:

```bash
id
printf 'HOME=%s USER=%s LOGNAME=%s\n' "$HOME" "$USER" "$LOGNAME"
pwd
```

Expected:

```text
uid=1001(astro) gid=1003(astro)
HOME=/home/astro USER=astro LOGNAME=astro
/opt/grace-orchestrator
```

- [ ] **Step 3: Verify Codex process and control socket ownership**

Run:

```bash
ps -eo user,uid,pid,ppid,args | rg 'codex.*app-server'
ss -xlpn | rg '/home/astro/.codex-api/app-server-control/app-server-control.sock'
stat -c '%U:%G %a %n' /home/astro/.codex-api/app-server-control/app-server-control.sock
```

Expected: the new app-server and proxy rows are owned by `astro` with UID
`1001`, and the active control socket is below `/home/astro/.codex-api`.

- [ ] **Step 4: Verify actual file creation identity**

Run:

```bash
probe=/opt/grace-orchestrator/.codex-owner-probe
: >"$probe"
stat -c '%U:%G %a %n' "$probe"
rm -f "$probe"
```

Expected owner while the probe exists: `astro:astro`.

### Task 3: Clean up and verify ownership

**Files:**
- Modify ownership only: root-owned paths below `/opt/grace-orchestrator`
- Stop: obsolete root Codex app-server and proxy processes after Task 2 passes

**Interfaces:**
- Consumes: A fully verified astro Codex connection.
- Produces: No root-owned workspace paths and no root Codex process mutating this workspace.

- [ ] **Step 1: Record the obsolete root Codex processes**

Run:

```bash
ps -eo user,uid,pid,ppid,lstart,args | rg '^root\s+0\s+.*codex.*app-server'
```

Expected: identifies the old root app-server started on July 10, 2026 and any
root proxy associated with the old connection.

- [ ] **Step 2: Stop only the obsolete root Codex app-server**

Run from the verified astro connection with sudo. These are the persistent
root app-server PIDs identified before cutover:

```bash
sudo kill -TERM 1521822 1521796
sleep 2
ps -p 1521822,1521796 -o user,uid,pid,ppid,args
```

Expected: `ps` prints only its header because both obsolete processes exited
cleanly. Do not use a broad `pkill codex` because astro Codex processes must
remain running. If either PID no longer identifies the recorded root Codex
command, stop and re-identify the process instead of signaling a reused PID.

- [ ] **Step 3: Repair only root-owned workspace paths**

Run:

```bash
sudo find /opt/grace-orchestrator -xdev -user root -exec chown astro:astro -- {} +
```

Expected: the known root-owned document and any root-owned paths created before
cutover become `astro:astro`; other owners are untouched.

- [ ] **Step 4: Run final ownership and Git checks**

Run:

```bash
find /opt/grace-orchestrator -xdev -user root -print
git -C /opt/grace-orchestrator status --short --branch
ps -eo user,uid,pid,ppid,args | rg 'codex.*app-server'
python3 scripts/grace_lint.py
```

Expected:

- The root-owned path search returns no output.
- Git status runs without `dubious ownership`.
- The active Codex app-server and proxy are owned by astro.
- `scripts/grace_lint.py` exits with code `0`.

- [ ] **Step 5: Commit only repository documentation created for this change**

Run:

```bash
git add docs/superpowers/plans/2026-07-12-codex-astro-ssh-switch.md
git commit -m "docs: plan Codex SSH switch to astro"
```

Expected: the plan is committed without including pre-existing modified or
untracked project files.
