#!/bin/sh
set -eu

: "${AUTHORIZED_KEY:?AUTHORIZED_KEY is required}"

printf '%s\n' "${AUTHORIZED_KEY}" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

exec /usr/sbin/sshd -D -e -p 2222

