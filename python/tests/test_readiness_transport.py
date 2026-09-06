"""Exercise the probe's real TLS/auth path without the generated SDK's memory cost."""

import json
import ssl
import subprocess
import sys
import threading
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from capi_provider_ssh import readiness


@pytest.fixture
def api_server(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(True, False, True, False, False, True, True, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    (tmp_path / "ca.crt").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "key.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    (tmp_path / "token").write_text("fixture-token-one")
    state = {"status": 200, "body": b'{"items": []}', "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"].append((self.command, self.path, self.headers.get("Authorization")))
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(state["body"])

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "ca.crt", tmp_path / "key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(readiness, "SERVICE_ACCOUNT_PATH", tmp_path)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "localhost")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", str(server.server_port))
    try:
        yield state, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_probe_authenticates_both_paths_and_reads_rotated_token(api_server):
    state, path = api_server
    with readiness.readiness_api() as api:
        assert api.list_cluster_custom_object(
            "infrastructure.alpininsight.ai", "v1beta1", "sshclusters", limit=1, _request_timeout=(1, 2)
        ) == {"items": []}
        (path / "token").write_text("fixture-token-two")
        state["body"] = b'{"status": {}}'
        assert api.get_cluster_custom_object(
            "kopf.dev", "v1", "clusterkopfpeerings", "capi-provider-ssh", _request_timeout=(1, 2)
        ) == {"status": {}}
    assert state["requests"] == [
        ("GET", "/apis/infrastructure.alpininsight.ai/v1beta1/sshclusters?limit=1", "Bearer fixture-token-one"),
        ("GET", "/apis/kopf.dev/v1/clusterkopfpeerings/capi-provider-ssh", "Bearer fixture-token-two"),
    ]


@pytest.mark.parametrize("status", [301, 401, 403, 404, 503])
def test_api_denial_and_redirects_fail_without_retry_or_body_disclosure(api_server, status):
    state, _ = api_server
    state.update(status=status, body=b"sensitive upstream diagnostic")
    with pytest.raises(readiness.NotReadyError, match=f"^Kubernetes API returned HTTP {status}$"):
        readiness.InClusterAPI()._get("/apis/test", (1, 2))
    assert len(state["requests"]) == 1


@pytest.mark.parametrize("body", [b"[]", b"null", b"x" * (readiness.MAX_API_RESPONSE + 1)])
def test_invalid_or_oversized_api_response_is_not_readiness(api_server, body):
    state, _ = api_server
    state["body"] = body
    with pytest.raises(readiness.NotReadyError):
        readiness.InClusterAPI()._get("/apis/test", (1, 2))


def test_malformed_json_is_rejected(api_server):
    state, _ = api_server
    state["body"] = b"invalid JSON"
    with pytest.raises(json.JSONDecodeError):
        readiness.InClusterAPI()._get("/apis/test", (1, 2))


def test_hostname_is_verified_before_sending_credentials(api_server, monkeypatch):
    state, _ = api_server
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "127.0.0.1")
    with pytest.raises(ssl.SSLCertVerificationError):
        readiness.InClusterAPI()._get("/apis/test", (1, 2))
    assert state["requests"] == []


def test_missing_trust_anchor_is_rejected(api_server):
    state, path = api_server
    (path / "ca.crt").write_text("")
    with pytest.raises(ssl.SSLError):
        readiness.InClusterAPI()._get("/apis/test", (1, 2))
    assert state["requests"] == []


def test_empty_token_never_becomes_an_anonymous_probe(api_server):
    state, path = api_server
    (path / "token").write_text("\n")
    with pytest.raises(readiness.NotReadyError, match="token is unavailable"):
        readiness.InClusterAPI()._get("/apis/test", (1, 2))
    assert state["requests"] == []


def test_in_cluster_probe_imports_no_generated_sdk():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import os, sys; os.environ['KUBERNETES_SERVICE_HOST']='localhost'; "
            "from capi_provider_ssh.readiness import readiness_api; "
            "client = readiness_api(); client.__enter__(); client.__exit__(None, None, None); "
            "assert 'kubernetes' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
