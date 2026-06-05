# GRACE Project Configuration

This document describes the project configuration file (`project.yaml`) used by GRACE orchestrator.

## Overview

The `project.yaml` file defines the project's identity, repository location, and runtime settings. It must be placed in one of these locations:

- `<repo_root>/grace/project.yaml` (recommended)
- `<repo_root>/prefect_grace/project.yaml` (legacy)

## Quick Start

Initialize a new project with:

```bash
grace init --project-key my-project --root /path/to/repo
```

This creates a `grace/` directory with a template `project.yaml` file.

## Configuration Schema

### Required Fields

These fields **must** be present in every configuration file:

#### `project_key` (string)

Unique identifier for the project. Used to namespace runtime resources (work pools, queues, state directories).

**Rules:**
- Cannot be empty or whitespace-only
- Should be lowercase with hyphens (e.g., `my-project`)
- Used in derived paths and resource names

**Example:**
```yaml
project_key: "my-awesome-project"
```

**Error if missing:**
```
ValueError: project_key is required in project.yaml.
Set project.key in your configuration.
Run 'grace init' to create a template.
```

#### `repo_root` (string)

Absolute path to the repository root directory.

**Rules:**
- Must be an absolute path (not relative)
- Must point to an existing directory
- Cannot be empty or whitespace-only

**Example:**
```yaml
repo_root: "/home/user/projects/my-project"
```

**Errors if invalid:**
```
# Missing or empty
ValueError: repo_root is required in project.yaml.
Set project.root in your configuration.
Run 'grace init' to create a template.

# Path doesn't exist
ValueError: repo_root does not exist: /path/to/repo
Ensure project.root points to your repository directory.

# Path is not a directory
ValueError: repo_root is not a directory: /path/to/file
```

### Optional Fields

These fields have sensible defaults and can be omitted:

#### `default_branch` (string)

Default branch name for the repository.

**Default:** `"main"`

**Example:**
```yaml
default_branch: "develop"
```

#### `grace_dir` (string)

Path to GRACE directory, relative to `repo_root`.

**Default:** `"grace"`

**Example:**
```yaml
grace_dir: "grace"
```

**Warning:** If this directory doesn't exist, a warning is logged but loading continues.

#### `packets_dir` (string)

Path to packets directory, relative to `repo_root`.

**Default:** `"grace/packets"`

**Example:**
```yaml
packets_dir: "grace/packets"
```

**Warning:** If this directory doesn't exist, a warning is logged but loading continues.

#### `workflow_runtime` (string)

Workflow orchestration runtime to use.

**Default:** `"prefect"`

**Example:**
```yaml
workflow_runtime: "prefect"
```

#### `prefect` (object)

Prefect-specific configuration. Required if `workflow_runtime` is `"prefect"`.

**Default values:**
```yaml
prefect:
  work_pool: "<project_key>-process"
  live_queue: "<project_key>-live"
  monitoring_queue: "<project_key>-monitoring"
```

**Example:**
```yaml
prefect:
  work_pool: "my-project-process"
  live_queue: "my-project-live"
  monitoring_queue: "my-project-monitoring"
```

#### `agent_executor` (object)

Agent executor configuration.

**Default values:**
```yaml
agent_executor:
  default: "codex-cli"
  command: "codex1"
```

**Example:**
```yaml
agent_executor:
  default: "codex-cli"
  command: "codex1"
  executors:
    - name: "custom-executor"
      command: "custom-cmd"
```

### Derived Fields

These fields are computed automatically and should not be set manually:

#### `runtime_state_root` (string)

Root directory for runtime state.

**Computed as:** `/var/lib/grace-orchestrator/<project_key>`

#### `artifact_root` (string)

Directory for storing artifacts.

**Computed as:** `/var/lib/grace-orchestrator/<project_key>/artifacts`

#### `worktree_root` (string)

Directory for git worktrees.

**Computed as:** `/var/lib/grace-orchestrator/<project_key>/worktrees`

## Complete Example

```yaml
# GRACE Project Configuration

# REQUIRED: Unique identifier for this project
project_key: "my-awesome-project"

# REQUIRED: Absolute path to repository root
repo_root: "/home/user/projects/my-awesome-project"

# Optional: Default branch (defaults to "main")
default_branch: "main"

# Optional: GRACE directory relative to repo_root (defaults to "grace")
grace_dir: "grace"

# Optional: Packets directory relative to repo_root (defaults to "grace/packets")
packets_dir: "grace/packets"

# Optional: Workflow runtime (defaults to "prefect")
workflow_runtime: "prefect"

# Prefect configuration (required if workflow_runtime is "prefect")
prefect:
  work_pool: "my-awesome-project-process"
  live_queue: "my-awesome-project-live"
  monitoring_queue: "my-awesome-project-monitoring"

# Agent executor configuration
agent_executor:
  default: "codex-cli"
  command: "codex1"
```

## Validation Rules

When loading a configuration, GRACE validates:

1. **Required fields present:** `project_key` and `repo_root` must be set
2. **Non-empty values:** Required fields cannot be empty or whitespace-only
3. **Path existence:** `repo_root` must point to an existing directory
4. **Path type:** `repo_root` must be a directory, not a file

**Warnings (non-fatal):**
- If `grace_dir` doesn't exist, a warning is logged
- If `packets_dir` doesn't exist, a warning is logged

## Migration from Old Configs

### Removing Magic Defaults

**Before (implicit defaults):**
```yaml
# project_key defaulted to "project"
# repo_root defaulted to current working directory
default_branch: "main"
```

**After (explicit required fields):**
```yaml
project_key: "my-project"
repo_root: "/absolute/path/to/repo"
default_branch: "main"
```

### Migration Steps

1. **Add `project_key`** if missing:
   ```yaml
   project_key: "your-project-name"
   ```

2. **Add `repo_root`** with absolute path:
   ```yaml
   repo_root: "/absolute/path/to/your/repo"
   ```

3. **Verify paths exist:**
   ```bash
   # Check that repo_root points to your repository
   ls -la /absolute/path/to/your/repo
   ```

4. **Test configuration:**
   ```bash
   grace --config /path/to/project.yaml status
   ```

### Common Migration Errors

**Error: "project_key is required"**

Add the project_key field:
```yaml
project_key: "my-project"
```

**Error: "repo_root is required"**

Add the repo_root field with an absolute path:
```yaml
repo_root: "/home/user/projects/my-project"
```

**Error: "repo_root does not exist"**

Ensure the path points to an existing directory:
```bash
mkdir -p /path/to/repo
```

Or update the path to point to the correct location:
```yaml
repo_root: "/correct/path/to/repo"
```

## Loading Configuration

### From Python

```python
from prefect_grace.platform.project_adapter import load_project_adapter

# Load from default location
config = load_project_adapter()

# Load from specific path
config = load_project_adapter("/path/to/project.yaml")

# Load with overrides
config = load_project_adapter(
    "/path/to/project.yaml",
    overrides={"default_branch": "develop"}
)
```

### From CLI

```bash
# Use default config location
grace status

# Use specific config file
grace --config /path/to/project.yaml status

# Use config in specific directory
grace --config /path/to/repo status
```

## Troubleshooting

### Configuration Not Found

**Error:**
```
FileNotFoundError: Project configuration file not found at /path/to/project.yaml
Run 'grace init' to create a template configuration.
```

**Solution:**
```bash
cd /path/to/repo
grace init --project-key my-project
```

### Invalid Path

**Error:**
```
ValueError: repo_root does not exist: /path/to/repo
```

**Solution:**
1. Check the path is correct
2. Ensure the directory exists
3. Use absolute paths, not relative paths

### Empty Required Field

**Error:**
```
ValueError: project_key is required in project.yaml.
```

**Solution:**
Add the missing field to your `project.yaml`:
```yaml
project_key: "my-project"
```

## Best Practices

1. **Use absolute paths** for `repo_root` to avoid ambiguity
2. **Keep project_key lowercase** with hyphens for consistency
3. **Version control** your `project.yaml` file
4. **Use `grace init`** to generate valid templates
5. **Test configuration** after changes with `grace status`
6. **Document custom settings** in comments within the file

## See Also

- [Configuration Migration Guide](CONFIGURATION_MIGRATION.md)
- [Quickstart Guide](QUICKSTART.md)
- [State Storage](STATE_STORAGE.md)
