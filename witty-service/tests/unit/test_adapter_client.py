from __future__ import annotations

import json

import httpx
import pytest

from witty_service.domain.errors import DomainError


def make_client(handler):
    from witty_service.adapter.client import AdapterClient

    return AdapterClient(
        base_url="http://adapter.test",
        timeout=1.5,
        transport=httpx.MockTransport(handler),
    )


def test_adapter_client_calls_rest_endpoints_successfully() -> None:
    requests: list[tuple[str, str, dict[str, str], bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        requests.append(
            (
                request.method,
                request.url.path,
                dict(request.url.params),
                body,
            )
        )

        if request.url.path == "/agent/start":
            assert request.method == "POST"
            assert request.url.params.get("reload") == "true"
            return httpx.Response(
                200,
                json={
                    "status": "running",
                    "runtime_type": "openclaw",
                    "config": {},
                    "already_running": False,
                },
            )

        if request.url.path == "/agent/status":
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "status": "running",
                    "runtime_type": "openclaw",
                },
            )

        if request.url.path == "/agent/sessions":
            assert request.method == "POST"
            assert json.loads(body.decode("utf-8")) == {}
            return httpx.Response(
                200,
                json={
                    "id": "session-1",
                    "context_initialized": True,
                },
            )

        if request.url.path == "/agent/stop":
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={
                    "status": "stopped",
                    "runtime_type": "openclaw",
                    "config": {},
                },
            )

        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = make_client(handler)

    assert client.start(reload=True)["status"] == "running"
    assert client.status()["runtime_type"] == "openclaw"
    assert client.create_session()["id"] == "session-1"
    assert client.stop()["status"] == "stopped"

    assert requests == [
        ("POST", "/agent/start", {"reload": "true"}, b""),
        ("GET", "/agent/status", {}, b""),
        ("POST", "/agent/sessions", {}, b"{}"),
        ("POST", "/agent/stop", {}, b""),
    ]


def test_send_message_stream_parses_sse_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/agent/sessions/session-1/messages"
        assert request.url.params.get("stream") == "true"
        assert json.loads(request.read().decode("utf-8")) == {"message": "hello"}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"type":"delta","delta":"he"}\n\n'
                'data: {"type":"error","message":"warn"}\n\n'
                'data: {"type":"done"}\n\n'
            ),
        )

    client = make_client(handler)

    events = list(client.send_message_stream("session-1", "hello"))

    assert events == [
        {"type": "delta", "delta": "he"},
        {"type": "error", "message": "warn"},
        {"type": "done"},
    ]


def test_send_message_stream_accepts_case_insensitive_sse_content_type_with_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "Text/Event-Stream; charset=utf-8"},
            text='data: {"type":"done"}\n\n',
        )

    client = make_client(handler)

    events = list(client.send_message_stream("session-1", "hello"))

    assert events == [{"type": "done"}]


def test_start_maps_network_errors_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        client.start()

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "network"
    assert exc_info.value.details["operation"] == "start"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["error_type"] == "ConnectError"
    assert "connection refused" in exc_info.value.details["error"]


def test_status_maps_server_errors_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={
                "code": "RUNTIME_UPSTREAM_ERROR",
                "message": "upstream exploded",
            },
        )

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        client.status()

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "http"
    assert exc_info.value.details["operation"] == "status"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["status_code"] == 502
    assert exc_info.value.details["body"] == {
        "code": "RUNTIME_UPSTREAM_ERROR",
        "message": "upstream exploded",
    }


def test_send_message_stream_rejects_non_sse_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"output": "not-a-stream"},
        )

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        list(client.send_message_stream("session-1", "hello"))

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "protocol"
    assert exc_info.value.details["operation"] == "send_message_stream"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["content_type"] == "application/json"


@pytest.mark.parametrize(
    ("stream_body", "expected_error_type"),
    [
        ('data: ["not","dict"]\n\n', "InvalidSSEPayload"),
        ('data: {"delta":"hello"}\n\n', "InvalidSSEPayload"),
    ],
)
def test_send_message_stream_rejects_invalid_payload_shape(
    stream_body: str,
    expected_error_type: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=stream_body,
        )

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        list(client.send_message_stream("session-1", "hello"))

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "protocol"
    assert exc_info.value.details["operation"] == "send_message_stream"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["error_type"] == expected_error_type


def test_send_message_stream_rejects_invalid_sse_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"type":"bogus"}\n\n',
        )

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        list(client.send_message_stream("session-1", "hello"))

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "protocol"
    assert exc_info.value.details["operation"] == "send_message_stream"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["error_type"] == "InvalidSSEEventType"


def test_send_message_stream_maps_non_2xx_response_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "code": "RUNTIME_UNAVAILABLE",
                "message": "adapter unavailable",
            },
        )

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        list(client.send_message_stream("session-1", "hello"))

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "http"
    assert exc_info.value.details["operation"] == "send_message_stream"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["status_code"] == 503
    assert exc_info.value.details["body"] == {
        "code": "RUNTIME_UNAVAILABLE",
        "message": "adapter unavailable",
    }


def test_send_message_stream_maps_network_errors_to_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("stream timed out", request=request)

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        list(client.send_message_stream("session-1", "hello"))

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "network"
    assert exc_info.value.details["operation"] == "send_message_stream"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["error_type"] == "ReadTimeout"


def test_send_message_stream_maps_invalid_json_to_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"type":\n\n',
        )

    client = make_client(handler)

    with pytest.raises(DomainError) as exc_info:
        list(client.send_message_stream("session-1", "hello"))

    assert exc_info.value.code == "ADAPTER_REQUEST_FAILED"
    assert exc_info.value.details["category"] == "protocol"
    assert exc_info.value.details["operation"] == "send_message_stream"
    assert exc_info.value.details["base_url"] == "http://adapter.test"
    assert exc_info.value.details["error_type"] == "JSONDecodeError"
