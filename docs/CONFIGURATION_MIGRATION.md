# GRACE Configuration Migration Guide

## Overview

Starting with GRACE Orchestrator v2.0, configuration files are no longer bundled inside the Python package. This change makes GRACE fully portable for external projects and eliminates hardcoded project-specific values.

This guide will help you migrate your existing GRACE installation to the new configuration system.

## Breaking Changes in v2.0

### 1. Configuration Files Not Bundled in Package

**Before (v1.x):**
- `runtime.yaml` and `project.yaml` were included in the installed package
- Configuration was loaded from `site-packages/prefect_grace/`

**After (v2.0):**
- Configuration files are excluded from the wheel distribution
- You must provide configuration in your project or home directory

### 2. Configuration Search Path Priority

GRACE now searches for configuration files in the following order:

**For `runtime.yaml`:**
1. Path specified in `GRACE_CONFIG_PATH` environment variable (highest priority)
2. `<project-root>/grace/runtime.yaml`
3. `~/.grace/runtime.yaml`
4. Package-local (deprecated, shows warning)

**For `project.yaml`:**
1. `<project-root>/grace/project.yaml`
2. `~/.grace/project.yaml`
3. Package-local (deprecated)

### 3. Default Work Pool Name Changed

**Before:** `astro-process` (hardcoded for Astro project)
**After:** `grace-process` (generic default)

If you have a Prefect work pool named `astro-process`, you should either:
- Rename it to `grace-process`, OR
- Override the work pool name in your configuration

### 4. Package-Local Config Deprecated

Loading configuration from the package installation directory now shows a deprecation warning:

```
DeprecationWarning: Loading config from package-local /path/to/site-packages/prefect_grace/runtime.yaml is deprecated.
Move config to grace/runtime.yaml or ~/.grace/runtime.yaml
```

## Migration Steps

### Step 1: Copy Configuration Templates

GRACE provides example configuration files in the `examples/` directory:

```bash
# For project-local configuration (recommended)
mkdir -p grace
cp /path/to/grace-orchestrator/examples/runtime.yaml.example grace/runtime.yaml
cp /path/to/grace-orchestrator/examples/project.yaml.example grace/project.yaml

# OR for user-level configuration
mkdir -p ~/.grace
cp /path/to/grace-orchestrator/examples/runtime.yaml.example ~/.grace/runtime.yaml
cp /path/to/grace-orchestrator/examples/project.yaml.example ~/.grace/project.yaml
```

### Step 2: Update Configuration Values

Edit the copied configuration files and replace placeholder values with your project-specific settings.

#### Minimal `runtime.yaml` Configuration

```yaml
api_url: http://127.0.0.1:4200/api
work_pool_name: grace-process  # or your custom work pool name
live_queue_name: grace-live
monitoring_queue_name: grace-monitoring
working_directory: /path/to/your/project
```

#### Full `project.yaml` Configuration

See `examples/project.yaml.example` for a complete annotated template.

Key sections to update:
- `project.key`: Your unique project identifier
- `project.root`: Absolute path to your project repository
- `runtime.state_root`: Where GRACE stores execution state
- `workflow_runtime.work_pool`: Your Prefect work pool name
- `codex.workdir`: Your project working directory

### Step 3: Update Work Pool Name

If you're using the old `astro-process` work pool:

**Option A: Rename the work pool (recommended)**
```bash
# In Prefect UI or via API, rename astro-process → grace-process
```

**Option B: Override in configuration**
```yaml
# In runtime.yaml or project.yaml
work_pool_name: astro-process  # Keep your existing work pool
```

### Step 4: Validate Configuration

Run the validation command to verify your configuration:

```bash
grace validate-config
```

Expected output:
```
Validating GRACE configuration...
✓ Runtime config loaded
  API URL: http://127.0.0.1:4200/api
  Work Pool: grace-process
  Working Dir: /path/to/your/project
✓ Project config loaded
  Project Key: my-project
  Repo Root: /path/to/your/project
  State Root: /var/lib/grace-orchestrator/my-project

✓ Configuration is valid!
```

### Step 5: Remove Package-Local Config (Optional)

Once you've verified your external configuration works, you can remove the deprecated package-local files:

```bash
# Find your site-packages directory
python -c "import prefect_grace; print(prefect_grace.__file__)"

# Remove deprecated config files (they're not used anymore)
rm /path/to/site-packages/prefect_grace/runtime.yaml
rm /path/to/site-packages/prefect_grace/project.yaml
```

## Configuration Priority

### Environment Variables

Environment variables have the highest priority and override file-based configuration:

- `GRACE_CONFIG_PATH`: Explicit path to `runtime.yaml`
- `PREFECT_GRACE_API_URL`: Prefect API URL
- `PREFECT_GRACE_WORK_POOL`: Work pool name
- `PREFECT_GRACE_LIVE_QUEUE`: Live queue name
- `PREFECT_GRACE_MONITORING_QUEUE`: Monitoring queue name
- `PREFECT_GRACE_WORKDIR`: Working directory

Example:
```bash
export GRACE_CONFIG_PATH=/custom/path/runtime.yaml
export PREFECT_GRACE_WORK_POOL=my-custom-pool
grace validate-config
```

### Configuration File Locations

**Project-local configuration** (recommended for team projects):
- Location: `<project-root>/grace/`
- Committed to version control
- Shared across team members
- Different per project

**User-level configuration** (recommended for personal use):
- Location: `~/.grace/`
- Not in version control
- Shared across all projects
- User-specific settings

**Explicit path** (for special cases):
- Set `GRACE_CONFIG_PATH` environment variable
- Useful for CI/CD, testing, or multi-environment setups

## Backward Compatibility

### Deprecation Timeline

- **v2.0**: Package-local config still works but shows deprecation warning
- **v2.1** (planned): Package-local config support will be removed
- **v3.0** (planned): Only external configuration will be supported

### Migration Support

The deprecation warning includes the path to the package-local config file being loaded, making it easy to identify which file needs to be migrated.

## Troubleshooting

### "No configuration found" Error

**Problem:** GRACE can't find any configuration files.

**Solution:**
1. Verify configuration files exist in one of the search paths
2. Check file permissions (must be readable)
3. Use `GRACE_CONFIG_PATH` to specify an explicit path
4. Run `grace validate-config` to see detailed error messages

### "Work pool not found" Error

**Problem:** Prefect can't find the work pool specified in configuration.

**Solution:**
1. Check your Prefect server is running
2. Verify the work pool exists: `prefect work-pool ls`
3. Create the work pool if needed: `prefect work-pool create grace-process --type process`
4. Update `work_pool_name` in your configuration

### Deprecation Warning Still Showing

**Problem:** You've created external config but still see the deprecation warning.

**Solution:**
1. Ensure your external config file is in the correct location
2. Check the file is named exactly `runtime.yaml` (not `runtime.yaml.example`)
3. Verify the file contains valid YAML and required fields
4. The package-local file is still being found first - remove it or move it

### Configuration Not Taking Effect

**Problem:** Changes to configuration files don't seem to apply.

**Solution:**
1. Check which config file is being loaded: `grace validate-config`
2. Verify you're editing the correct file (check search path priority)
3. Environment variables override file configuration - check your env vars
4. Restart any running GRACE workers or processes

### Path Issues

**Problem:** Paths in configuration don't work or cause errors.

**Solution:**
1. Use absolute paths, not relative paths
2. Expand `~` to full home directory path
3. Ensure directories exist and are writable
4. Check file permissions on state_root and artifact_root

## Examples

### Example 1: Single Project Setup

For a single project with local configuration:

```bash
cd /path/to/my-project
mkdir -p grace
cat > grace/runtime.yaml <<EOF
api_url: http://127.0.0.1:4200/api
work_pool_name: grace-process
live_queue_name: grace-live
monitoring_queue_name: grace-monitoring
working_directory: /path/to/my-project
EOF

grace validate-config
```

### Example 2: Multi-Project Setup

For multiple projects sharing user-level configuration:

```bash
mkdir -p ~/.grace
cat > ~/.grace/runtime.yaml <<EOF
api_url: http://127.0.0.1:4200/api
work_pool_name: grace-process
live_queue_name: grace-live
monitoring_queue_name: grace-monitoring
# working_directory will default to current directory
EOF

# Each project can override with project-local config if needed
cd /path/to/project-a
mkdir -p grace
cat > grace/runtime.yaml <<EOF
working_directory: /path/to/project-a
EOF
```

### Example 3: CI/CD Setup

For CI/CD pipelines with environment-specific configuration:

```bash
# In CI/CD environment
export GRACE_CONFIG_PATH=/ci/config/runtime.yaml
export PREFECT_GRACE_API_URL=http://prefect-server:4200/api
export PREFECT_GRACE_WORKDIR=/ci/workspace

grace validate-config
grace submit-packets --execute
```

## Getting Help

If you encounter issues during migration:

1. Run `grace validate-config` for detailed diagnostics
2. Check the deprecation warning message for the old config path
3. Review the configuration templates in `examples/`
4. Consult the main README.md for configuration documentation
5. File an issue on GitHub with the output of `grace validate-config`

## Summary Checklist

- [ ] Copy configuration templates to `grace/` or `~/.grace/`
- [ ] Update configuration values for your project
- [ ] Update work pool name from `astro-process` to `grace-process` (or override)
- [ ] Run `grace validate-config` to verify configuration
- [ ] Test GRACE commands with new configuration
- [ ] Remove or ignore package-local config files
- [ ] Update documentation and team onboarding guides
- [ ] Commit `grace/` directory to version control (if using project-local config)
