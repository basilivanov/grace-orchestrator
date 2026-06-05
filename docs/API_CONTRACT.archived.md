# `API_CONTRACT.md` is archived.

The hand-written API contract has been **superseded by auto-generated docs**.

| Old | New |
|-----|-----|
| `docs/API_CONTRACT.md` | [`docs/openapi.json`](./openapi.json) — OpenAPI 3 spec from the FastAPI app |
| `docs/API_CONTRACT.md` | Swagger UI at `/docs` on the running API |
| (state machine tables) | [`docs/state-diagram.md`](./state-diagram.md) + [`docs/packet-states.md`](./packet-states.md) |
| (git history) | [`docs/.archived/API_CONTRACT.md`](./.archived/API_CONTRACT.md) — kept for history |

Regenerate the auto-generated docs with:
    make docs           # writes docs/openapi.json, state-diagram.md, packet-states.md
    make docs-check     # CI: exits 1 if any of the above drift

Do not hand-edit `docs/openapi.json`, `docs/state-diagram.md`, or
`docs/packet-states.md` — re-run `make docs` instead.
