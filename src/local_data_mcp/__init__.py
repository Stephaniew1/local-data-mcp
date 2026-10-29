"""local-data-mcp: expose a local SQLite database to LLM clients over MCP."""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_DB = os.environ.get("LOCAL_DATA_DB", "data/store.db")


def main() -> None:
    parser = argparse.ArgumentParser(prog="local-data-mcp", description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to the SQLite file (env: LOCAL_DATA_DB)")
    parser.add_argument("--seed", action="store_true", help="Create a sample database at --db and exit")
    parser.add_argument("--force", action="store_true", help="With --seed, overwrite an existing file")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio for desktop clients (default); streamable-http to serve over HTTP",
    )
    args = parser.parse_args()

    if args.seed:
        from .seed import seed

        path = seed(args.db, overwrite=args.force)
        # stdout is the MCP channel in stdio mode, so all logging goes to stderr.
        print(f"Seeded sample database at {path}", file=sys.stderr)
        return

    from .server import create_server

    create_server(args.db).run(transport=args.transport)
