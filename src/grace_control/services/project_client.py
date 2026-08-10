# ############################################################################
# AI_HEADER: project_client — bounded project-local GRACE API transport
# ROLE: Sends explicit project-scoped HTTP or Unix-socket requests from the
#       Admin Hub. It never opens project databases, worktrees or private files.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide a reusable, bounded, JSON-safe client for one ProjectContext.
# inputs: ProjectContext, relative API paths, timeout settings and optional
#          HTTP transport/factory for tests or Unix-socket communication.
# returns: ProjectApiResult with normalized success or isolated error details.
# side_effects: Performs project-local network requests.
# emitted_logs: project_api_request, project_api_error.
# error_behavior: Converts timeout, connection, HTTP and JSON failures to a
#                 typed result; never exposes transport credentials.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ProjectApiResult
#   - class: ProjectClient
#     methods:
#       - request_json
#       - get_json
#       - get_health
#       - health
#       - get_openapi
#       - get_capabilities
#       - close
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("project_client")


# START_BLOCK_RESULT
@dataclass(frozen=True, slots=True)
class ProjectApiResult:
    """Normalized result for one project-local API request."""

    project_key: str
    ok: bool
    payload: dict[str, Any] | None = None
    error_class: str | None = None
    error: str | None = None
    http_status: int | None = None
    last_attempt_at: str = ""
    headers: dict[str, str] | None = None


# END_BLOCK_RESULT


# START_BLOCK_CLIENT
class ProjectClient:
    """Bounded transport client tied to one immutable project context."""

    def __init__(
        self,
        context: ProjectContext,
        *,
        connect_timeout: float = 1.0,
        read_timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] | None = None,
    ) -> None:
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("project API timeouts must be positive")
        self.context = context
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self._transport = transport
        self._client_factory = client_factory or httpx.AsyncClient

    # START_FUNCTION_CONTRACT
    # name: request_json
    # purpose: Perform one bounded JSON request for this explicit project.
    # inputs: path — relative API path; method — HTTP method; payload — optional
    #          JSON request body for methods that accept one.
    # returns: ProjectApiResult with decoded object or normalized error.
    # side_effects: Performs one HTTP or Unix-socket request; never retries.
    # emitted_logs: project_api_request, project_api_error.
    # error_behavior: Converts transport/status/JSON failures to error_class.
    # END_FUNCTION_CONTRACT
    async def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Mapping[str, Any] | None = None,
    ) -> ProjectApiResult:
        if not path or not path.startswith("/"):
            raise ValueError("project API path must be an absolute path component")
        normalized_method = method.upper()
        attempted_at = _now_iso()
        _log.info(
            "project_api_request",
            project_key=self.context.key,
            method=normalized_method,
            path=path,
        )
        client_kwargs = self._client_kwargs()
        try:
            async with self._client_factory(**client_kwargs) as client:
                response = await client.request(normalized_method, path, json=payload)
        except httpx.TimeoutException as exc:
            return self._error_result("timeout", _safe_error(exc), attempted_at)
        except httpx.ConnectError as exc:
            return self._error_result("api_offline", _safe_error(exc), attempted_at)
        except httpx.NetworkError as exc:
            return self._error_result("api_offline", _safe_error(exc), attempted_at)
        except httpx.HTTPError as exc:
            return self._error_result("api_offline", _safe_error(exc), attempted_at)
        except Exception as exc:
            _log.error(
                "project_api_error",
                project_key=self.context.key,
                error_class="client_error",
            )
            return self._error_result("client_error", _safe_error(exc), attempted_at)

        if response.status_code < 200 or response.status_code >= 300:
            error_class = "api_offline" if response.status_code >= 500 else "http_error"
            error_message = f"project API returned HTTP {response.status_code}"
            try:
                error_payload = response.json()
            except (ValueError, TypeError):
                error_payload = {}
            if isinstance(error_payload, Mapping):
                typed_error = error_payload.get("error")
                if isinstance(typed_error, Mapping):
                    error_class = str(typed_error.get("code") or error_class)[:80]
                    error_message = _safe_error(typed_error.get("message") or error_message)
            return self._error_result(
                error_class,
                error_message,
                attempted_at,
                http_status=response.status_code,
            )
        try:
            decoded = response.json()
        except (ValueError, TypeError) as exc:
            return self._error_result("malformed_response", _safe_error(exc), attempted_at,
                                      http_status=response.status_code)
        if not isinstance(decoded, dict):
            return self._error_result(
                "malformed_response",
                "project API JSON response must be an object",
                attempted_at,
                http_status=response.status_code,
            )
        return ProjectApiResult(
            project_key=self.context.key,
            ok=True,
            payload=decoded,
            http_status=response.status_code,
            last_attempt_at=attempted_at,
            headers=_safe_headers(response.headers),
        )

    # START_FUNCTION_CONTRACT
    # name: get_json
    # purpose: Convenience wrapper for one idempotent project-local GET.
    # inputs: path — relative API path.
    # returns: ProjectApiResult from request_json.
    # side_effects: Performs one GET request; never retries.
    # emitted_logs: project_api_request, project_api_error.
    # error_behavior: Same normalized errors as request_json.
    # END_FUNCTION_CONTRACT
    async def get_json(self, path: str) -> ProjectApiResult:
        return await self.request_json(path, method="GET")

    # START_FUNCTION_CONTRACT
    # name: get_health
    # purpose: Read the existing project-local admin health contract, falling
    #          back to lightweight liveness when an older runtime lacks it.
    # inputs: None.
    # returns: ProjectApiResult containing a JSON health object or typed error.
    # side_effects: Performs one GET, or one fallback GET for HTTP 404 only.
    # emitted_logs: project_api_request, project_api_error.
    # error_behavior: Never raises transport/JSON errors; returns normalized result.
    # END_FUNCTION_CONTRACT
    async def get_health(self) -> ProjectApiResult:
        result = await self.get_json("/api/admin/system/health")
        if result.http_status == 404:
            result = await self.get_json("/health")
        if result.ok and result.payload and not _has_identity(result.payload):
            identity = await self.get_json("/api/admin/project-identity")
            if identity.ok and identity.payload:
                result = ProjectApiResult(
                    project_key=result.project_key,
                    ok=True,
                    payload={**result.payload, **identity.payload},
                    http_status=result.http_status,
                    last_attempt_at=result.last_attempt_at,
                    headers=result.headers,
                )
        return result

    # START_FUNCTION_CONTRACT
    # name: health
    # purpose: Backward-compatible alias for get_health.
    # inputs: None.
    # returns: ProjectApiResult containing project health.
    # side_effects: Performs the bounded health request.
    # emitted_logs: project_api_request, project_api_error.
    # error_behavior: Returns normalized project API errors.
    # END_FUNCTION_CONTRACT
    async def health(self) -> ProjectApiResult:
        return await self.get_health()

    # START_FUNCTION_CONTRACT
    # name: get_openapi
    # purpose: Retrieve the project-local FastAPI OpenAPI document through the
    #          same bounded transport used for all project reads.
    # inputs: None.
    # returns: ProjectApiResult containing the OpenAPI object or a typed error.
    # side_effects: Performs one bounded GET /openapi.json request.
    # emitted_logs: project_api_request, project_api_error.
    # error_behavior: Converts transport, HTTP and malformed JSON failures.
    # END_FUNCTION_CONTRACT
    async def get_openapi(self) -> ProjectApiResult:
        return await self.get_json("/openapi.json")

    # START_FUNCTION_CONTRACT
    # name: get_capabilities
    # purpose: Retrieve the optional-feature capability document, if supported
    #          by a project runtime.
    # inputs: None.
    # returns: ProjectApiResult; HTTP 404 remains a typed unavailable result.
    # side_effects: Performs one bounded GET /api/admin/capabilities request.
    # emitted_logs: project_api_request, project_api_error.
    # error_behavior: Converts transport, HTTP and malformed JSON failures.
    # END_FUNCTION_CONTRACT
    async def get_capabilities(self) -> ProjectApiResult:
        return await self.get_json("/api/admin/capabilities")

    # START_FUNCTION_CONTRACT
    # name: close
    # purpose: Close hook for callers that own a client lifecycle.
    # inputs: None.
    # returns: None.
    # side_effects: None; requests use short-lived managed clients.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    async def close(self) -> None:
        return None

    def _client_kwargs(self) -> dict[str, Any]:
        timeout = httpx.Timeout(
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=self.read_timeout,
            pool=self.connect_timeout,
        )
        headers: dict[str, str] = {}
        if self.context.api_token:
            headers["x-grace-api-token"] = self.context.api_token
        if self.context.api_password and not self.context.api_token:
            headers["x-grace-api-password"] = self.context.api_password
        kwargs: dict[str, Any] = {"timeout": timeout, "headers": headers}
        if self.context.api_socket is not None:
            kwargs["transport"] = self._transport or httpx.AsyncHTTPTransport(
                uds=str(self.context.api_socket)
            )
            kwargs["base_url"] = "http://grace-project.local"
        else:
            kwargs["transport"] = self._transport
            kwargs["base_url"] = self.context.api_url
        return {key: value for key, value in kwargs.items() if value is not None}

    def _error_result(
        self,
        error_class: str,
        error: str,
        attempted_at: str,
        *,
        http_status: int | None = None,
    ) -> ProjectApiResult:
        _log.error(
            "project_api_error",
            project_key=self.context.key,
            error_class=error_class,
        )
        return ProjectApiResult(
            project_key=self.context.key,
            ok=False,
            error_class=error_class,
            error=error,
            http_status=http_status,
            last_attempt_at=attempted_at,
        )


# END_BLOCK_CLIENT


# START_BLOCK_HELPERS
def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_error(error: Exception) -> str:
    text = str(error).replace("\n", " ").strip()
    return text[:240] or error.__class__.__name__


def _has_identity(payload: Mapping[str, Any]) -> bool:
    return any(
        payload.get(key) not in (None, "")
        for key in ("project_key", "project_name", "project_root", "target_repo_root")
    )


def _safe_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    """Keep a bounded, non-credential response-header subset for inspectors."""
    allowed = frozenset({
        "cache-control",
        "content-length",
        "content-type",
        "date",
        "etag",
        "last-modified",
    })
    return {
        str(key).lower(): str(value)[:240]
        for key, value in headers.items()
        if str(key).lower() in allowed
    }


# END_BLOCK_HELPERS
