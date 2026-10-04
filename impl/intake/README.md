# abra intake

Write-only endpoint so any VM on the internal network can record a note into abra.

- `POST http://10.0.0.200:8040/store`, internal network only (ufw: 10.0.0.0/24).
- No read endpoints. The response is the new content id and nothing else.
- One token per VM, accepted only from that VM's IP.
- Writes go to scope `intake` (per token), category `intake/<vm>`, `created_by urn:abra:intake:<vm>`.
- Limits: 60 writes/min per VM, 64K chars per note.

## Call it

```bash
curl -s -X POST http://10.0.0.200:8040/store \
  -H "Authorization: Bearer $ABRA_INTAKE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"some-name","content":"the note","qualifier":"short summary","date":"today"}'
# {"id": 1234}
```

`name`: lowercase letters, digits, hyphens. `qualifier` and `date` (YYYY-MM-DD or `today`) are optional.

Read it back from the dev VM: `abra --scope intake about some-name`, or `abra search`.

## Tokens (on the dev VM)

```bash
cd /opt/shared/repos/abra/impl/intake
../.venv/bin/python tokens.py add vm-300-platform 10.0.0.30   # prints token once
../.venv/bin/python tokens.py list
../.venv/bin/python tokens.py revoke vm-300-platform
```

Only sha256 hashes are kept, in `tokens.json` (600, gitignored). Changes apply without restart.

## Service

`tmp-abra-intake.service`, runs as the abra owner with `impl/.env`.

Known gap: the service uses the full abra Postgres role from `impl/.env`. An insert-only role
on `content`, `bindings`, `catcode_registry` would limit what a bug in this service could do.
