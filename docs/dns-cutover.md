# DNS Cutover (Staging -> Production)

This runbook covers swapping DNS so staging becomes production, while keeping
the previous production environment as rollback backup.

## Decision

- Promote staging to production traffic.
- Keep old production available as backup (read-only preferred).
- Tear down old production only after review acceptance and rollback-window end.

## Preconditions

- Staging and production run the same release artifact and config schema.
- Database migrations are validated.
- Secrets and certificates for public endpoints are present in staging.
- Monitoring and alerting for staging are production-grade.
- DNS TTL is reduced ahead of cutover (for example 60s).

## Cutover

```bash
# Example: switch primary record to staging endpoint
# Replace host/target with your actual values.
dnsctl record update app.example.com --type CNAME --target staging.example.net --ttl 60
```

Operational actions:

1. Freeze non-essential deploys during cutover.
2. Switch DNS records from old production to staging.
3. Keep old production online as rollback target.
4. Run smoke checks (health, login, critical API paths, background jobs).

## Rollback

If issues are found, point DNS back to old production immediately.

```bash
dnsctl record update app.example.com --type CNAME --target prod-old.example.net --ttl 60
```

Then:
- Confirm user traffic recovers.
- Keep staging for debugging.
- Retry cutover only after root cause and fix validation.

## Teardown of Old Production

Do not tear down old production before the customer sprint review.

Safe teardown gate:
- Customer review completed successfully.
- Rollback no longer required for agreed window.
- Backup/restore test from the new production is successful.

After gate approval:
1. Take final backup/snapshot of old production.
2. Export logs/audit data needed for retention.
3. Decommission old production resources.
