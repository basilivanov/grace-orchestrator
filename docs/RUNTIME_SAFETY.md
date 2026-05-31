# Runtime Safety: PrefectAPIContext

## Problem Statement

Global environment variable mutation poses significant risks in multi-runtime and multi-process scenarios:

- **State Pollution**: Direct mutation of `os.environ["PREFECT_API_URL"]` affects the entire process
- **Race Conditions**: Multiple concurrent operations can interfere with each other
- **Cleanup Failures**: Exception paths may skip restoration, leaving incorrect state
- **Debugging Difficulty**: Global state makes it hard to track which code set which value
- **Multi-Project Conflicts**: Different projects or runtimes in the same process can conflict

### Previous Pattern (Unsafe)

```python
# Direct mutation - no cleanup
os.environ["PREFECT_API_URL"] = api_url
deployment.apply()

# Manual cleanup - error-prone
old_api_url = os.environ.get("PREFECT_API_URL")
try:
    os.environ["PREFECT_API_URL"] = api_url
    deployment.apply()
finally:
    if old_api_url is not None:
        os.environ["PREFECT_API_URL"] = old_api_url
    else:
        os.environ.pop("PREFECT_API_URL", None)
```

## Solution: PrefectAPIContext

The `PrefectAPIContext` context manager provides safe, stack-based environment variable management:

- **Automatic Restoration**: Previous value restored on exit, even with exceptions
- **Stack-Based Nesting**: Supports nested contexts with proper restoration order
- **Leak Detection**: Warns if contexts are not properly exited at process termination
- **Input Validation**: Rejects empty or None URLs
- **Thread-Safe**: Each context tracks its own state

## Usage Examples

### Basic Usage

```python
from prefect_grace.runtime import PrefectAPIContext

# Temporary API URL for deployment
with PrefectAPIContext(api_url):
    deployment.apply()
# Automatically restored
```

### Nested Contexts

```python
with PrefectAPIContext(runtime1.api_url):
    # Operations on runtime1
    deployment1.apply()
    
    with PrefectAPIContext(runtime2.api_url):
        # Operations on runtime2
        deployment2.apply()
    
    # Back to runtime1 context
    deployment1.update()

# Original value restored
```

### Exception Safety

```python
try:
    with PrefectAPIContext(api_url):
        deployment.apply()
        raise SomeError()  # Context still restores properly
except SomeError:
    pass  # Environment is clean
```

### Convenience Function

```python
from prefect_grace.runtime import prefect_api_context

with prefect_api_context(api_url):
    deployment.apply()
```

## Migration Guide

### Pattern 1: Direct Mutation

**Before:**
```python
os.environ["PREFECT_API_URL"] = api_url
deployment.apply()
```

**After:**
```python
with PrefectAPIContext(api_url):
    deployment.apply()
```

### Pattern 2: Manual Try/Finally

**Before:**
```python
old_api_url = os.environ.get("PREFECT_API_URL")
try:
    os.environ["PREFECT_API_URL"] = api_url
    deployment.apply()
    client.update_deployment(...)
finally:
    if old_api_url is not None:
        os.environ["PREFECT_API_URL"] = old_api_url
    else:
        os.environ.pop("PREFECT_API_URL", None)
```

**After:**
```python
with PrefectAPIContext(api_url):
    deployment.apply()
    client.update_deployment(...)
```

### Pattern 3: Nested Operations

**Before:**
```python
os.environ["PREFECT_API_URL"] = runtime.api_url

with get_client(sync_client=True) as client:
    deployment = client.read_deployment_by_name(name)
    flow_run = client.create_flow_run_from_deployment(...)
```

**After:**
```python
with PrefectAPIContext(runtime.api_url):
    with get_client(sync_client=True) as client:
        deployment = client.read_deployment_by_name(name)
        flow_run = client.create_flow_run_from_deployment(...)
```

## Leak Detection

The context manager registers an `atexit` handler to detect leaked contexts:

```python
# This will trigger a warning at process exit
ctx = PrefectAPIContext(api_url)
ctx.__enter__()
# Forgot to call __exit__!
```

**Warning message:**
```
PrefectAPIContext leak detected: 1 context(s) not properly exited at process termination.
```

This helps catch programming errors where contexts are not properly managed.

## Implementation Details

### Stack-Based Tracking

The context manager maintains a class-level stack to track nested contexts:

```python
class PrefectAPIContext:
    _stack: list[tuple[str, Optional[str]]] = []
    
    def __enter__(self):
        self.previous_value = os.environ.get("PREFECT_API_URL")
        os.environ["PREFECT_API_URL"] = self.api_url
        PrefectAPIContext._stack.append((self.api_url, self.previous_value))
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        PrefectAPIContext._stack.pop()
        if self.previous_value is not None:
            os.environ["PREFECT_API_URL"] = self.previous_value
        else:
            os.environ.pop("PREFECT_API_URL", None)
        return False  # Don't suppress exceptions
```

### Depth Tracking

For debugging, you can check the current nesting depth:

```python
depth = PrefectAPIContext.current_depth()
print(f"Currently {depth} contexts deep")
```

## Best Practices

1. **Always use the context manager**: Never mutate `os.environ["PREFECT_API_URL"]` directly
2. **Keep contexts focused**: Wrap only the operations that need the specific API URL
3. **Avoid long-lived contexts**: Exit contexts as soon as the operation completes
4. **Test nested scenarios**: Ensure your code works correctly with nested contexts
5. **Check for leaks**: Run tests with leak detection enabled to catch errors

## Migrated Code Locations

All 8 mutation sites have been refactored to use `PrefectAPIContext`:

1. `prefect_grace/deploy_live.py:71` - `_apply_deployment` function
2. `prefect_grace/deploy_live.py:154` - `main` function
3. `prefect_grace/tasks/prefect_runs.py:35` - `list_recent_feature_flow_runs` function
4. `prefect_grace/platform/runtime_adapter.py:277` - `FeatureSubmitter.__call__`
5. `prefect_grace/platform/runtime_adapter.py:351` - `E2EPacketSubmitter.__call__`
6. `prefect_grace/platform/runtime_adapter.py:428` - `ManagedPacketSubmitter.__call__`
7. `prefect_grace/platform/runtime_adapter.py:632` - `apply_managed_packet_deployment_helper`
8. `prefect_grace/platform/runtime_adapter.py:667` - (removed manual finally block)

## Testing

Comprehensive tests are available in `prefect_grace/tests/test_env_context.py`:

```bash
pytest src/prefect_grace/tests/test_env_context.py -v
```

Test coverage includes:
- Basic enter/exit behavior
- Nested contexts
- Exception handling
- Input validation
- Convenience function
- No initial value scenarios
- Multi-level restoration
- Depth tracking
