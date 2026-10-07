# 01 — stdio baseline

Reference implementation of the standard tool set. One server process per client, started by the
host over stdin/stdout.

```mermaid
flowchart LR
    host["MCP host: Inspector / Claude"] -->|"stdin/stdout JSON-RPC"| server["python -m mcpserver"]
    server --> tools["tools.py: ReplicaTools"]
    tools --> store["SessionCounterStore (process memory)"]
```

## Layout
| File | Contents |
|---|---|
| `src/mcpserver/tools.py` | `ReplicaTools` (the four tools), `SessionCounterStore` |
| `src/mcpserver/schemas.py` | `ReplicaIdentity`, `ConfirmationAnswer` |
| `src/mcpserver/app.py` | `create_mcp_server()` |
| `src/mcpserver/config.py` | `ServerSettings` (`MCP_*` env vars) |
| `tests/test_tools.py` | every tool through the SDK in-memory client |
| `tests/test_stdio_entry_point.py` | starts `python -m mcpserver` as a subprocess and talks stdio |

## Run
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest          # unit + stdio tests, coverage gate 80%
.\.venv\Scripts\ruff.exe check . ; .\.venv\Scripts\ruff.exe format --check .
npx @modelcontextprotocol/inspector .\.venv\Scripts\python.exe -m mcpserver   # manual check
```

## Results (2026-10-06)
| Check | Result |
|---|---|
| Unit tests | 12 passed |
| Coverage | 100% |
| ruff | clean |

The HTTP harness does not apply to stdio; the subprocess test covers the real entry point.

## When to use in production
Local tools for a single user (file system, local CLIs). Scaling is not a concern: each client gets
its own process.
