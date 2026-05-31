"""Tests for runtime_adapter dual sync/async API."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from prefect_grace.platform.runtime_adapter import (
    DryRunRuntime,
    PrefectRuntimeAdapter,
)


class TestDryRunRuntimeDualAPI:
    """Test DryRunRuntime sync and async methods."""

    def test_read_run_status_sync(self):
        """Test sync version of read_run_status."""
        runtime = DryRunRuntime()
        run_ref = {"run_id": "test-123"}

        result = runtime.read_run_status(run_ref)

        assert result["run_id"] == "test-123"
        assert result["state"] == "DRY_RUN"
        assert result["status"] == "simulated"

    @pytest.mark.asyncio
    async def test_read_run_status_async(self):
        """Test async version of read_run_status."""
        runtime = DryRunRuntime()
        run_ref = {"run_id": "test-456"}

        result = await runtime.read_run_status_async(run_ref)

        assert result["run_id"] == "test-456"
        assert result["state"] == "DRY_RUN"
        assert result["status"] == "simulated"


class TestPrefectRuntimeAdapterDualAPI:
    """Test PrefectRuntimeAdapter sync and async methods."""

    def test_read_run_status_sync_missing_run_id(self):
        """Test sync version returns error for missing run_id."""
        runtime = PrefectRuntimeAdapter()
        run_ref = {}

        result = runtime.read_run_status(run_ref)

        assert "error" in result
        assert "run_id missing" in result["error"]

    @pytest.mark.asyncio
    async def test_read_run_status_async_missing_run_id(self):
        """Test async version returns error for missing run_id."""
        runtime = PrefectRuntimeAdapter()
        run_ref = {}

        result = await runtime.read_run_status_async(run_ref)

        assert "error" in result
        assert "run_id missing" in result["error"]

    def test_read_run_status_sync_uses_run_async_safe(self):
        """Test sync version uses run_async_safe helper."""
        runtime = PrefectRuntimeAdapter()
        run_ref = {"run_id": "flow-run-123"}

        # Mock run_async_safe to return a successful result
        with patch("prefect_grace.platform.runtime_adapter.run_async_safe") as mock_run_async_safe:
            mock_run_async_safe.return_value = {
                "run_id": "flow-run-123",
                "state": "Completed",
                "status": "COMPLETED",
            }

            # Mock the Prefect import to succeed
            mock_get_client = MagicMock()
            with patch.dict("sys.modules", {"prefect.client.orchestration": MagicMock(get_client=mock_get_client)}):
                result = runtime.read_run_status(run_ref)

        assert result["run_id"] == "flow-run-123"
        assert result["state"] == "Completed"
        assert result["status"] == "COMPLETED"
        mock_run_async_safe.assert_called_once()

    def test_read_run_status_sync_handles_event_loop_error(self):
        """Test sync version returns clear error when called from async context."""
        runtime = PrefectRuntimeAdapter()
        run_ref = {"run_id": "flow-run-123"}

        # Mock run_async_safe to raise the event loop error
        with patch("prefect_grace.platform.runtime_adapter.run_async_safe") as mock_run_async_safe:
            mock_run_async_safe.side_effect = RuntimeError(
                "Cannot use run_async_safe() from within an event loop. "
                "You are calling a sync method from an async context. "
                "Please use the async version of this method instead (e.g., read_run_status_async())."
            )

            # Mock the Prefect import to succeed
            mock_get_client = MagicMock()
            with patch.dict("sys.modules", {"prefect.client.orchestration": MagicMock(get_client=mock_get_client)}):
                result = runtime.read_run_status(run_ref)

        assert "error" in result
        assert "Cannot call sync method from async context" in result["error"]
        assert "guidance" in result
        assert "read_run_status_async()" in result["guidance"]

    def test_read_run_status_sync_handles_general_exception(self):
        """Test sync version handles general exceptions."""
        runtime = PrefectRuntimeAdapter()
        run_ref = {"run_id": "flow-run-123"}

        # Mock run_async_safe to raise a general exception
        with patch("prefect_grace.platform.runtime_adapter.run_async_safe") as mock_run_async_safe:
            mock_run_async_safe.side_effect = Exception("Network error")

            # Mock the Prefect import to succeed
            mock_get_client = MagicMock()
            with patch.dict("sys.modules", {"prefect.client.orchestration": MagicMock(get_client=mock_get_client)}):
                result = runtime.read_run_status(run_ref)

        assert "error" in result
        assert "Network error" in result["error"]

    def test_read_run_status_sync_handles_import_error(self):
        """Test sync version handles Prefect import error."""
        runtime = PrefectRuntimeAdapter()
        run_ref = {"run_id": "flow-run-123"}

        # The import will fail naturally since prefect is not installed
        with pytest.raises(RuntimeError) as exc_info:
            runtime.read_run_status(run_ref)

        assert "Prefect client unavailable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_read_run_status_async_handles_import_error(self):
        """Test async version handles Prefect import error."""
        runtime = PrefectRuntimeAdapter()
        run_ref = {"run_id": "flow-run-123"}

        # The import will fail naturally since prefect is not installed
        with pytest.raises(RuntimeError) as exc_info:
            await runtime.read_run_status_async(run_ref)

        assert "Prefect client unavailable" in str(exc_info.value)


class TestRuntimeAdapterAbstractMethods:
    """Test that both sync and async methods are required."""

    def test_abstract_methods_exist(self):
        """Test that WorkflowRuntime defines both sync and async abstract methods."""
        from prefect_grace.platform.runtime_adapter import WorkflowRuntime
        import inspect

        # Get abstract methods
        abstract_methods = WorkflowRuntime.__abstractmethods__

        # Both versions should be abstract
        assert "read_run_status" in abstract_methods
        assert "read_run_status_async" in abstract_methods

    def test_implementations_provide_both_methods(self):
        """Test that concrete implementations provide both methods."""
        # DryRunRuntime
        dry_run = DryRunRuntime()
        assert hasattr(dry_run, "read_run_status")
        assert hasattr(dry_run, "read_run_status_async")
        assert callable(dry_run.read_run_status)
        assert callable(dry_run.read_run_status_async)

        # PrefectRuntimeAdapter
        prefect_runtime = PrefectRuntimeAdapter()
        assert hasattr(prefect_runtime, "read_run_status")
        assert hasattr(prefect_runtime, "read_run_status_async")
        assert callable(prefect_runtime.read_run_status)
        assert callable(prefect_runtime.read_run_status_async)
