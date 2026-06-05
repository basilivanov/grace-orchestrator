# Async/Sync Patterns in GRACE

## Problem

Python's `asyncio.run()` creates a new event loop, which fails if called from within an existing event loop. This causes runtime errors when sync methods that use `asyncio.run()` are called from async contexts.

**Example of the problem:**

```python
# This fails if called from async context
def read_status(self, run_id):
    async def _fetch():
        async with get_client() as client:
            return await client.read_flow_run(run_id)
    
    return asyncio.run(_fetch())  # ❌ RuntimeError if already in event loop
```

## Solution: Dual API Pattern

Provide both sync and async versions of methods that need to interact with async APIs:

1. **Sync version** (`read_run_status`): Uses `run_async_safe()` helper that detects existing event loops
2. **Async version** (`read_run_status_async`): Directly awaits the coroutine

## Usage Examples

### From Synchronous Code

Use the sync version:

```python
from prefect_grace.platform.runtime_adapter import PrefectRuntimeAdapter

runtime = PrefectRuntimeAdapter()
run_ref = {"run_id": "flow-run-123"}

# Call sync version
status = runtime.read_run_status(run_ref)
print(status)  # {"run_id": "...", "state": "Completed", "status": "COMPLETED"}
```

### From Asynchronous Code

Use the async version:

```python
from prefect_grace.platform.runtime_adapter import PrefectRuntimeAdapter

runtime = PrefectRuntimeAdapter()
run_ref = {"run_id": "flow-run-123"}

# Call async version
async def check_status():
    status = await runtime.read_run_status_async(run_ref)
    print(status)  # {"run_id": "...", "state": "Completed", "status": "COMPLETED"}

await check_status()
```

## Error Handling

### Calling Sync from Async Context

If you accidentally call the sync version from an async context, you'll get a clear error:

```python
async def bad_example():
    runtime = PrefectRuntimeAdapter()
    run_ref = {"run_id": "flow-run-123"}
    
    # ❌ This will return an error dict
    status = runtime.read_run_status(run_ref)
    
    # status = {
    #     "error": "Cannot call sync method from async context",
    #     "guidance": "Use read_run_status_async() instead",
    #     "details": "Cannot use run_async_safe() from within an event loop..."
    # }
```

### Exception Propagation

Both versions propagate exceptions from the underlying async operations:

```python
# Sync version
try:
    status = runtime.read_run_status(run_ref)
    if "error" in status:
        print(f"Error: {status['error']}")
except RuntimeError as e:
    print(f"Runtime error: {e}")

# Async version
try:
    status = await runtime.read_run_status_async(run_ref)
    if "error" in status:
        print(f"Error: {status['error']}")
except RuntimeError as e:
    print(f"Runtime error: {e}")
```

## Implementation Guide

### For New Methods

When adding a new method that needs to call async APIs:

1. **Add both sync and async versions to the abstract base class:**

```python
from abc import ABC, abstractmethod

class WorkflowRuntime(ABC):
    @abstractmethod
    def my_method(self, arg: str) -> dict:
        """Sync version - use from sync contexts."""
        pass
    
    @abstractmethod
    async def my_method_async(self, arg: str) -> dict:
        """Async version - use from async contexts."""
        pass
```

2. **Implement sync version using `run_async_safe()`:**

```python
from prefect_grace.runtime.async_helpers import run_async_safe

class MyRuntime(WorkflowRuntime):
    def my_method(self, arg: str) -> dict:
        async def _fetch():
            # Your async implementation
            async with get_client() as client:
                return await client.do_something(arg)
        
        try:
            return run_async_safe(_fetch())
        except RuntimeError as e:
            if "event loop" in str(e).lower():
                return {
                    "error": "Cannot call sync method from async context",
                    "guidance": "Use my_method_async() instead",
                    "details": str(e),
                }
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}
```

3. **Implement async version directly:**

```python
class MyRuntime(WorkflowRuntime):
    async def my_method_async(self, arg: str) -> dict:
        try:
            async with get_client() as client:
                return await client.do_something(arg)
        except Exception as e:
            return {"error": str(e)}
```

### For Existing Code

When migrating existing code that uses `asyncio.run()`:

**Before:**
```python
def read_status(self, run_id):
    async def _fetch():
        async with get_client() as client:
            return await client.read_flow_run(run_id)
    
    return asyncio.run(_fetch())  # ❌ Fails in async context
```

**After:**
```python
from prefect_grace.runtime.async_helpers import run_async_safe

def read_status(self, run_id):
    async def _fetch():
        async with get_client() as client:
            return await client.read_flow_run(run_id)
    
    try:
        return run_async_safe(_fetch())
    except RuntimeError as e:
        if "event loop" in str(e).lower():
            return {
                "error": "Cannot call sync method from async context",
                "guidance": "Use read_status_async() instead",
                "details": str(e),
            }
        return {"error": str(e)}

async def read_status_async(self, run_id):
    async with get_client() as client:
        return await client.read_flow_run(run_id)
```

## Testing

### Test Both Versions

Always test both sync and async versions:

```python
import pytest

def test_my_method_sync():
    """Test sync version from sync context."""
    runtime = MyRuntime()
    result = runtime.my_method("test")
    assert result["status"] == "ok"

@pytest.mark.asyncio
async def test_my_method_async():
    """Test async version from async context."""
    runtime = MyRuntime()
    result = await runtime.my_method_async("test")
    assert result["status"] == "ok"

@pytest.mark.asyncio
async def test_my_method_sync_from_async_context():
    """Test sync version returns error from async context."""
    runtime = MyRuntime()
    result = runtime.my_method("test")
    assert "error" in result
    assert "async context" in result["error"]
```

## API Reference

### `async_helpers` Module

#### `is_in_event_loop() -> bool`

Detect if currently running inside an event loop.

**Returns:** `True` if inside an event loop, `False` otherwise.

**Example:**
```python
from prefect_grace.runtime.async_helpers import is_in_event_loop

if is_in_event_loop():
    print("In async context")
else:
    print("In sync context")
```

#### `run_async_safe(coro: Coroutine) -> T`

Safely run an async coroutine from a sync context.

**Args:**
- `coro`: The coroutine to execute

**Returns:** The result of the coroutine execution

**Raises:**
- `RuntimeError`: If called from within an existing event loop

**Example:**
```python
from prefect_grace.runtime.async_helpers import run_async_safe

async def fetch_data():
    return {"data": "value"}

# From sync context
result = run_async_safe(fetch_data())
print(result)  # {"data": "value"}
```

## Best Practices

1. **Always provide both versions** when a method needs to call async APIs
2. **Use clear naming**: `method_name()` for sync, `method_name_async()` for async
3. **Document which version to use** in docstrings
4. **Return error dicts** instead of raising exceptions when possible
5. **Include guidance** in error messages pointing to the correct version
6. **Test both versions** and the error case (sync called from async)

## Migration Checklist

When migrating code to use the dual API pattern:

- [ ] Identify all uses of `asyncio.run()` in sync methods
- [ ] Create async version of each method
- [ ] Update sync version to use `run_async_safe()`
- [ ] Add error handling for async context detection
- [ ] Update abstract base class to include async version
- [ ] Update all implementations (DryRunRuntime, PrefectRuntimeAdapter, etc.)
- [ ] Add tests for both sync and async versions
- [ ] Add test for sync version called from async context
- [ ] Update documentation and docstrings
- [ ] Search codebase for callers and update if needed
