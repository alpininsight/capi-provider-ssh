"""Real TLS download faults and the no-apply boundary of Kind prerequisites."""

import hashlib
import ssl
import threading
import time
import traceback
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from tests.kind import install


@pytest.fixture
def asset_server(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    ca = tmp_path / "ca.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key = tmp_path / "key.pem"
    private_key.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    body = b"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: fixture\n"
    state = {"body": body, "statuses": [200], "requests": [], "unblock": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"].append(self.headers.get("Authorization"))
            status = state["statuses"][min(len(state["requests"]) - 1, len(state["statuses"]) - 1)]
            self.send_response(status)
            if state.get("redirect_http"):
                self.send_header("Location", "http://localhost/asset")
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            if state.get("stall"):
                state["unblock"].wait(timeout=3)
            with suppress(BrokenPipeError, ConnectionResetError, ssl.SSLError):
                self.wfile.write(state["body"])

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(ca, private_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("CURL_CA_BUNDLE", str(ca))
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    # User curl settings must not inject headers or extra requests into CI.
    (tmp_path / ".curlrc").write_text('header = "Authorization: fixture-must-not-be-sent"\n')
    monkeypatch.setenv("CURL_HOME", str(tmp_path))
    asset = {
        "name": "fixture.yaml",
        "url": f"https://localhost:{server.server_port}/asset",
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    try:
        yield state, asset
    finally:
        state["unblock"].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_transient_failures_retry_then_verify_one_complete_asset(asset_server):
    state, asset = asset_server
    state["statuses"] = [504, 503, 200]
    assert install.download_asset(asset) == state["body"]
    assert state["requests"] == [None, None, None]


@pytest.mark.parametrize("status,expected_requests", [(404, 1), (504, 3)])
def test_failures_are_bounded_without_response_or_url_disclosure(asset_server, status, expected_requests):
    state, asset = asset_server
    state.update(statuses=[status], body=b"private-response-sentinel")
    asset["url"] += "?private-query-sentinel"
    with pytest.raises(RuntimeError, match="Pinned asset download failed") as caught:
        install.download_asset(asset)
    text = "".join(traceback.format_exception(caught.value))
    assert "private-response-sentinel" not in text
    assert "private-query-sentinel" not in text
    assert len(state["requests"]) == expected_requests


def test_wrong_hash_is_not_retried_or_accepted(asset_server):
    state, asset = asset_server
    state["body"] = b"tampered fixture"
    with pytest.raises(RuntimeError, match="hash mismatch"):
        install.download_asset(asset)
    assert len(state["requests"]) == 1


def test_untrusted_tls_never_fetches_a_manifest(asset_server, monkeypatch):
    state, asset = asset_server
    monkeypatch.delenv("CURL_CA_BUNDLE")
    with pytest.raises(RuntimeError, match="download failed"):
        install.download_asset(asset)
    assert state["requests"] == []


def test_https_redirect_cannot_downgrade_to_http(asset_server):
    state, asset = asset_server
    state.update(statuses=[302], redirect_http=True)
    with pytest.raises(RuntimeError, match="download failed"):
        install.download_asset(asset)
    assert len(state["requests"]) == 1


@pytest.mark.parametrize(
    "url", ["http://localhost/asset", "file:///etc/passwd", "https://user:password@localhost/asset"]
)
def test_untrusted_url_forms_are_rejected_before_download(monkeypatch, url):
    execute = Mock()
    monkeypatch.setattr(install.subprocess, "run", execute)
    with pytest.raises(RuntimeError, match="uncredentialed HTTPS"):
        install.download_asset({"name": "fixture.yaml", "url": url, "sha256": "0" * 64})
    execute.assert_not_called()


def test_slow_body_is_killed_within_the_whole_download_budget(asset_server, monkeypatch):
    state, asset = asset_server
    state["stall"] = True
    monkeypatch.setattr(install, "DOWNLOAD_BUDGET_SECONDS", 1)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="time budget"):
        install.download_asset(asset)
    assert time.monotonic() - start < 2


def test_oversized_asset_is_not_accepted(asset_server, monkeypatch):
    _, asset = asset_server
    monkeypatch.setattr(install, "MAX_ASSET_BYTES", 8)
    with pytest.raises(RuntimeError, match="download failed"):
        install.download_asset(asset)


def test_all_assets_are_validated_before_any_apply(monkeypatch, tmp_path):
    monkeypatch.setenv("KIND_TEST_KUBECONFIG", str(tmp_path / "explicit-kubeconfig"))
    monkeypatch.setenv("KIND_TEST_ARTIFACTS", str(tmp_path / "artifacts"))
    guard = Mock()
    execute = Mock()
    calls = []

    def download(asset):
        guard.assert_called_once_with(str(tmp_path / "explicit-kubeconfig"), "unused")
        calls.append(asset["name"])
        if len(calls) == 2:
            raise RuntimeError("Upstream asset hash mismatch: fixture.yaml")
        return b"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: fixture\n"

    monkeypatch.setattr(install, "Runtime", guard)
    monkeypatch.setattr(install, "run", execute)
    monkeypatch.setattr(install, "download_asset", download)
    with pytest.raises(RuntimeError, match="hash mismatch"):
        install.main()
    assert len(calls) == 2
    execute.assert_not_called()


def test_wrong_context_stops_before_fetch(monkeypatch, tmp_path):
    monkeypatch.setenv("KIND_TEST_KUBECONFIG", str(tmp_path / "wrong-context"))
    download = Mock()
    execute = Mock()
    monkeypatch.setattr(install, "Runtime", Mock(side_effect=RuntimeError("not the disposable Kind context")))
    monkeypatch.setattr(install, "download_asset", download)
    monkeypatch.setattr(install, "run", execute)
    with pytest.raises(RuntimeError, match="not the disposable"):
        install.main()
    download.assert_not_called()
    execute.assert_not_called()
