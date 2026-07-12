# ############################################################################
# AI_HEADER: codex_astro_ssh_switch_design - move remote Codex execution from root to astro
# ROLE: Defines the server preparation, connection cutover, verification, and rollback for the Codex SSH identity change.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Specify how the Codex Desktop SSH connection and app-server processes move from root to astro without losing recovery access.
# inputs: Current SSH public key fingerprint, astro account, Codex installation, and /opt/grace-orchestrator workspace.
# returns: An approved operational design and measurable acceptance checks.
# side_effects: Implementation will add one SSH public key for astro, stop obsolete root Codex processes, and repair root-owned workspace files.
# emitted_logs: none.
# error_behavior: Cutover stops before root cleanup when astro authentication or Codex startup verification fails.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - section: Context
#   - section: Decision
#   - section: Cutover sequence
#   - section: Verification
#   - section: Rollback
# END_MODULE_MAP

# Codex SSH Execution as astro

## Context

The active Codex app-server runs as `root` with `HOME=/root` and stores its
control socket below `/root/.codex-api`. The repository
`/opt/grace-orchestrator` is owned by `astro:astro`. Root-side file replacement
therefore creates `root:root` files and makes Git reject the repository as
dubiously owned.

The current Codex client authenticates with the ED25519 key whose fingerprint
is `SHA256:AeQ921yO2uuSKXqOmBygoZsT3U/1akg4xj8l9wEajXc`. That key is authorized
for `root` but is not yet authorized for `astro`.

## Decision

Authorize only the current Codex client key for `astro`, then change the client
SSH username from `root` to `astro`. Both `codex app-server` and
`codex app-server proxy` must inherit UID 1001, GID 1003, and
`HOME=/home/astro` naturally from SSH. No post-edit ownership hook or broad ACL
workaround will be introduced.

Root SSH access remains unchanged until the astro connection and app-server are
verified. Disabling root login is outside this change.

## Cutover sequence

1. Create `/home/astro/.ssh/authorized_keys` containing the exact currently
   used client public key and no unrelated root keys.
2. Set `/home/astro/.ssh` to `astro:astro` mode `0700` and
   `authorized_keys` to `astro:astro` mode `0600`.
3. Validate the effective SSHD configuration for user `astro` without changing
   or restarting SSHD.
4. Change the Codex connection username to `astro` and reconnect.
5. In the new connection, verify UID, GID, HOME, working directory, app-server
   ownership, and the control socket location.
6. Only after successful verification, stop the obsolete root Codex app-server
   and proxy processes associated with this connection.
7. Repair only root-owned paths below `/opt/grace-orchestrator`; do not perform
   a blanket recursive ownership rewrite of unrelated owners.

Existing modified and untracked repository files are not altered or included
in infrastructure commits.

## Verification

The cutover is accepted when all checks pass:

- `id -u` returns `1001` and `id -g` returns `1003` in the Codex executor.
- `HOME` is `/home/astro` and the Codex control socket is below
  `/home/astro/.codex-api`.
- Codex processes that can mutate the workspace are owned by `astro`.
- `find /opt/grace-orchestrator -xdev -user root -print` returns no paths.
- `git -C /opt/grace-orchestrator status` works as `astro` without a
  `dubious ownership` exception.
- A disposable file created and removed through the executor is owned by
  `astro:astro` while it exists.

## Rollback

If astro authentication or app-server startup fails, retain the current root
key and root app-server, reconnect as root, and correct only the astro SSH key
or environment. Root processes are not stopped and workspace ownership is not
changed until the astro path has passed verification.
