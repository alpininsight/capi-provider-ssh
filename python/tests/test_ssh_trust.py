"""Real loopback SSH handshakes prove trust checks happen before commands."""

import asyncssh
import pytest

from capi_provider_ssh.ssh import SSHClient


@pytest.fixture
async def endpoint(tmp_path):
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    calls = []

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            calls.append("auth")
            return True

        def public_key_auth_supported(self):
            return True

        def validate_public_key(self, username, key):
            return key == client_key.convert_to_public()

    def execute(process):
        calls.append(process.command)
        process.stdout.write("verified\n")
        process.exit(0)

    server = await asyncssh.create_server(
        Server,
        "127.0.0.1",
        0,
        server_host_keys=[host_key],
        process_factory=execute,
        sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=str(tmp_path)),
    )
    port = server.get_port()
    known_hosts = f"[127.0.0.1]:{port} {host_key.export_public_key().decode()}"
    yield (
        {
            "address": "127.0.0.1",
            "port": port,
            "key": client_key.export_private_key().decode(),
            "known_hosts": known_hosts,
        },
        calls,
        tmp_path,
    )
    server.close()
    await server.wait_closed()


async def test_verified_host_allows_command_and_private_upload(endpoint):
    options, calls, root = endpoint
    async with await SSHClient.connect(**options) as conn:
        result = await conn.execute("echo test")
        await conn.upload("private bootstrap data", "/bootstrap.sh")
    assert result.success and result.stdout == "verified\n"
    assert calls == ["auth", "echo test"]
    assert (root / "bootstrap.sh").stat().st_mode & 0o777 == 0o600


async def test_changed_host_key_is_rejected_before_authentication(endpoint):
    options, calls, _ = endpoint
    wrong_key = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    options["known_hosts"] = f"[127.0.0.1]:{options['port']} {wrong_key}"
    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        await SSHClient.connect(**options)
    assert not calls


@pytest.mark.parametrize("known_hosts", [None, "", "   "])
async def test_missing_trust_fails_before_network(endpoint, known_hosts):
    options, calls, _ = endpoint
    options["known_hosts"] = known_hosts
    with pytest.raises(ValueError, match="known_hosts"):
        await SSHClient.connect(**options)
    assert not calls


async def test_revoked_host_key_is_rejected(endpoint):
    options, calls, _ = endpoint
    options["known_hosts"] = "@revoked " + options["known_hosts"]
    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        await SSHClient.connect(**options)
    assert not calls
