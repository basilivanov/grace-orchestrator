"""Tests for PrefectAPIContext environment variable management."""

import os
import pytest

from prefect_grace.runtime import PrefectAPIContext, prefect_api_context


class TestPrefectAPIContext:
    """Test suite for PrefectAPIContext context manager."""

    def test_basic_context(self):
        """Test basic enter/exit behavior."""
        original_value = os.environ.get("PREFECT_API_URL")
        test_url = "https://test.prefect.cloud/api/accounts/test"

        with PrefectAPIContext(test_url):
            assert os.environ["PREFECT_API_URL"] == test_url

        # Should restore to original value
        if original_value is None:
            assert "PREFECT_API_URL" not in os.environ
        else:
            assert os.environ["PREFECT_API_URL"] == original_value

    def test_nested_contexts(self):
        """Test stack-based nesting."""
        url1 = "https://api1.prefect.cloud/api/accounts/test1"
        url2 = "https://api2.prefect.cloud/api/accounts/test2"
        url3 = "https://api3.prefect.cloud/api/accounts/test3"

        with PrefectAPIContext(url1):
            assert os.environ["PREFECT_API_URL"] == url1
            assert PrefectAPIContext.current_depth() == 1

            with PrefectAPIContext(url2):
                assert os.environ["PREFECT_API_URL"] == url2
                assert PrefectAPIContext.current_depth() == 2

                with PrefectAPIContext(url3):
                    assert os.environ["PREFECT_API_URL"] == url3
                    assert PrefectAPIContext.current_depth() == 3

                # Should restore to url2
                assert os.environ["PREFECT_API_URL"] == url2
                assert PrefectAPIContext.current_depth() == 2

            # Should restore to url1
            assert os.environ["PREFECT_API_URL"] == url1
            assert PrefectAPIContext.current_depth() == 1

        # Should restore to original (None in this test)
        assert PrefectAPIContext.current_depth() == 0

    def test_exception_handling(self):
        """Test restoration on exception."""
        original_value = os.environ.get("PREFECT_API_URL")
        test_url = "https://test.prefect.cloud/api/accounts/test"

        with pytest.raises(ValueError, match="test exception"):
            with PrefectAPIContext(test_url):
                assert os.environ["PREFECT_API_URL"] == test_url
                raise ValueError("test exception")

        # Should restore even after exception
        if original_value is None:
            assert "PREFECT_API_URL" not in os.environ
        else:
            assert os.environ["PREFECT_API_URL"] == original_value

        # Stack should be clean
        assert PrefectAPIContext.current_depth() == 0

    def test_empty_url_rejected(self):
        """Test input validation."""
        with pytest.raises(ValueError, match="api_url cannot be empty or None"):
            PrefectAPIContext("")

        with pytest.raises(ValueError, match="api_url cannot be empty or None"):
            PrefectAPIContext(None)

    def test_convenience_function(self):
        """Test alternative API."""
        test_url = "https://test.prefect.cloud/api/accounts/test"

        with prefect_api_context(test_url):
            assert os.environ["PREFECT_API_URL"] == test_url

        assert PrefectAPIContext.current_depth() == 0

    def test_no_initial_value(self):
        """Test handling when env var doesn't exist initially."""
        # Ensure PREFECT_API_URL is not set
        original_value = os.environ.pop("PREFECT_API_URL", None)
        try:
            assert "PREFECT_API_URL" not in os.environ

            test_url = "https://test.prefect.cloud/api/accounts/test"
            with PrefectAPIContext(test_url):
                assert os.environ["PREFECT_API_URL"] == test_url

            # Should remove the key entirely
            assert "PREFECT_API_URL" not in os.environ
        finally:
            # Restore original value if it existed
            if original_value is not None:
                os.environ["PREFECT_API_URL"] = original_value

    def test_restoration_to_different_value(self):
        """Test multi-level restoration."""
        # Set initial value
        initial_url = "https://initial.prefect.cloud/api/accounts/initial"
        os.environ["PREFECT_API_URL"] = initial_url

        try:
            url1 = "https://api1.prefect.cloud/api/accounts/test1"
            url2 = "https://api2.prefect.cloud/api/accounts/test2"

            with PrefectAPIContext(url1):
                assert os.environ["PREFECT_API_URL"] == url1

                with PrefectAPIContext(url2):
                    assert os.environ["PREFECT_API_URL"] == url2

                # Should restore to url1, not initial_url
                assert os.environ["PREFECT_API_URL"] == url1

            # Should restore to initial_url
            assert os.environ["PREFECT_API_URL"] == initial_url
        finally:
            # Clean up
            os.environ.pop("PREFECT_API_URL", None)

    def test_depth_tracking(self):
        """Test stack depth verification."""
        assert PrefectAPIContext.current_depth() == 0

        url1 = "https://api1.prefect.cloud/api/accounts/test1"
        url2 = "https://api2.prefect.cloud/api/accounts/test2"

        with PrefectAPIContext(url1):
            assert PrefectAPIContext.current_depth() == 1

            with PrefectAPIContext(url2):
                assert PrefectAPIContext.current_depth() == 2

            assert PrefectAPIContext.current_depth() == 1

        assert PrefectAPIContext.current_depth() == 0

    def test_context_manager_protocol(self):
        """Test that __enter__ returns self."""
        test_url = "https://test.prefect.cloud/api/accounts/test"
        ctx = PrefectAPIContext(test_url)

        with ctx as returned:
            assert returned is ctx
            assert os.environ["PREFECT_API_URL"] == test_url

    def test_multiple_sequential_contexts(self):
        """Test multiple sequential (non-nested) contexts."""
        original_value = os.environ.get("PREFECT_API_URL")

        url1 = "https://api1.prefect.cloud/api/accounts/test1"
        url2 = "https://api2.prefect.cloud/api/accounts/test2"
        url3 = "https://api3.prefect.cloud/api/accounts/test3"

        with PrefectAPIContext(url1):
            assert os.environ["PREFECT_API_URL"] == url1

        with PrefectAPIContext(url2):
            assert os.environ["PREFECT_API_URL"] == url2

        with PrefectAPIContext(url3):
            assert os.environ["PREFECT_API_URL"] == url3

        # Should restore to original
        if original_value is None:
            assert "PREFECT_API_URL" not in os.environ
        else:
            assert os.environ["PREFECT_API_URL"] == original_value

        assert PrefectAPIContext.current_depth() == 0
