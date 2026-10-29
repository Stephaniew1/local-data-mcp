# local-data-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes a local SQLite database to LLM clients
(Claude Desktop, Claude Code, MCP Inspector, …) as **structured, read-only tools**.

Every tool returns a Pydantic model, so clients get both an `outputSchema` up front and typed
`structuredContent` in each result (plus a JSON text fallback for older clients).

## Quick start

```bash
uv sync
uv run local-data-mcp --seed          # creates data/store.db with sample store data
uv run pytest                         # 16 tests, incl. a real stdio round-trip
uv run local-data-mcp                 # serve over stdio
```

Point it at your own database with `--db path/to/file.db` or `LOCAL_DATA_DB=...`. The generic tools
(`list_tables`, `describe_table`, `run_query`) work on any SQLite file. The domain tools assume the
sample schema, so replace them with ones that fit your data (see "Adapting" below).

## What it exposes

| Kind | Name | Purpose |
|---|---|---|
| tool | `list_tables` | Tables + row counts |
| tool | `describe_table` | Columns, FKs, row count, 3 sample rows |
| tool | `run_query` | Ad-hoc read-only SQL (`SELECT`/`WITH`/`EXPLAIN`), row-limited |
| tool | `search_products` | Filter by name, category, price range, stock |
| tool | `get_customer` | Customer by id/email + lifetime value + recent orders with items |
| tool | `sales_summary` | Revenue/units/orders grouped by month, category or product, with a date range |
| resource | `schema://database` | Full DDL |
| prompt | `analyze_sales` | Canned analysis workflow using the tools above |

All tools carry `readOnlyHint` / `idempotentHint` annotations.

## Safety model

* Connections open the file with `mode=ro`, so SQLite itself refuses writes.
* `run_query` also installs a SQLite **authorizer** that denies everything except
  SELECT/READ/FUNCTION/RECURSIVE. That covers cases like `WITH x AS (...) DELETE ...`,
  `ATTACH` and pragmas.
* Only one statement is allowed per call, and results are capped at `limit` (max 1000), with a `truncated` flag.
* Table names in `describe_table` are checked against `sqlite_master` and never interpolated from raw input.
* Bad input becomes a tool error (`isError: true`) that the model can read and recover from, not a crash.

## Connect a client

**Claude Code**

```bash
claude mcp add local-data -- uv --directory /ABSOLUTE/PATH/local-data-mcp run local-data-mcp
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "local-data": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/local-data-mcp", "run", "local-data-mcp"],
      "env": { "LOCAL_DATA_DB": "/ABSOLUTE/PATH/local-data-mcp/data/store.db" }
    }
  }
}
```

**MCP Inspector** (interactive debugging)

```bash
npx @modelcontextprotocol/inspector uv run local-data-mcp
```

**Over HTTP**: `uv run local-data-mcp --transport streamable-http` serves at `http://127.0.0.1:8000/mcp`.

> In stdio mode, stdout carries the protocol. Never `print()` to stdout in server code; log to stderr.

## Layout

```
src/local_data_mcp/
  __init__.py   CLI entry point (--db, --seed, --transport)
  server.py     MCPServer: tools, resource, prompt
  models.py     Pydantic output models -> outputSchema / structuredContent
  db.py         read-only SQLite access + authorizer
  seed.py       deterministic sample database
tests/          in-memory client tests + stdio end-to-end test
```

## Adapting to your own data

1. Swap `Database` in `db.py` for your source (CSV via `csv`/DuckDB, a JSON folder, Postgres, …).
2. Model each answer shape in `models.py`.
3. Add one `@mcp.tool()` per question the model should be able to answer. Give each a clear docstring
   (it becomes the tool description) and `Annotated[..., Field(description=...)]` parameters
   (they become the input schema).
