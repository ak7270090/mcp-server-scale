# MCP Scaling Lab

The same small MCP server built once per scaling pattern, each measured with one shared harness.
Plan: [PLAN.md](PLAN.md).

| Folder | Pattern | Status |
|---|---|---|
| [test-harness](test-harness/) | Phase 0: shared test + load harness | done |
| [01-stdio-baseline](01-stdio-baseline/) | stdio, one process per client | done |
| [02-streamable-http-single](02-streamable-http-single/) | Streamable HTTP, one replica (and the 4-worker failure) | done |
| [03-sticky-session-lb](03-sticky-session-lb/) | 3 replicas behind HAProxy cookie / nginx prefix / Envoy envelope | done |
| [04-gateway-queue-workers](04-gateway-queue-workers/) | gateway + NATS JetStream workers + autoscaler | done |
| [05-api-to-mcp-gateway](05-api-to-mcp-gateway/) | REST/gRPC ↔ MCP translation with curation, redaction, REST facade (Part B) | done |

## Comparison (short load profile, `get_replica_id`)
| Setup | Affinity | Failover keeps state | Resumability | Elicitation | Load failures | p95 |
|---|---|---|---|---|---|---|
| 02 one worker | ✅ | — | ✅ | ✅ | 0 / 706 | 69 ms |
| 02 four workers | ❌ | — | ⚠ random | ⚠ random | 12 / 731 (`DELETE`) | 99 ms |
| 03 HAProxy cookie | ✅ | ❌ (`404`) | ✅ | ✅ | 0 / 1,234 | 68 ms |
| 03 nginx prefix | ✅ | ❌ (`502`) | ✅ | ✅ | 0 / 1,270 | 68 ms |
| 03 Envoy envelope | ✅ | ❌ (`404`) | ✅ | ✅ | 0 / 1,237 | 67 ms |
| 04 gateway + 3 workers | ✅ (KV) | ✅ | ✅ | ✅ (asked once, variant B) | 0 / 569 | 3,800 ms |

Phase 4's latency is head-of-line blocking: one job per worker, so quick calls wait behind
2-second slow jobs. See its README.

Part B (phase 5) is not a scaling pattern: it measures translation overhead instead —
`GET /orders/1` p95 12 ms directly vs 75 ms as an MCP tool through the gateway.

## Setup
Windows, Python 3.11, one `venv` per folder (`python -m venv .venv` then
`pip install -e ".[dev]"`), Docker Desktop for phases 2+. Shared lint rules: [ruff.toml](ruff.toml).
Tracing backend: [compose.observability.yaml](compose.observability.yaml) (Jaeger, UI on
`localhost:16686`).

After Docker testing: `docker compose down`, stop all containers, quit Docker Desktop,
`wsl --shutdown`.
