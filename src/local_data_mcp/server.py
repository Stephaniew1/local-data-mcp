"""MCP server exposing a local SQLite database as structured tools."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from .db import Database, QueryError
from .models import (
    ColumnInfo,
    CustomerDetail,
    ForeignKey,
    Order,
    OrderItem,
    Product,
    ProductSearchResult,
    QueryResult,
    SalesBucket,
    SalesSummary,
    TableInfo,
    TableList,
    TableSchema,
)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = """\
This server gives read-only access to a local store database (customers, products, orders, order_items).
Prefer the purpose-built tools (search_products, get_customer, sales_summary). Use list_tables and
describe_table to learn the schema before writing SQL for run_query. Revenue excludes cancelled orders.
"""

ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


def create_server(db_path: str) -> MCPServer:
    db = Database(db_path)
    mcp = MCPServer(name="local-data", instructions=INSTRUCTIONS, version="0.1.0")

    # ---------------------------------------------------------------- generic tools

    @mcp.tool(annotations=READ_ONLY)
    def list_tables() -> TableList:
        """List every table in the database with its row count."""
        return TableList(
            tables=[
                TableInfo(name=t, row_count=db.fetch_one(f'SELECT COUNT(*) AS n FROM "{t}"')["n"])
                for t in db.table_names()
            ]
        )

    @mcp.tool(annotations=READ_ONLY)
    def describe_table(table: Annotated[str, Field(description="Table name from list_tables")]) -> TableSchema:
        """Show a table's columns, foreign keys, row count and a few example rows."""
        try:
            table = db.require_table(table)
        except QueryError as exc:
            raise ToolError(str(exc)) from exc
        columns = [
            ColumnInfo(
                name=c["name"],
                type=c["type"],
                nullable=not c["notnull"],
                primary_key=bool(c["pk"]),
                default=c["dflt_value"],
            )
            for c in db.fetch_all(f'PRAGMA table_info("{table}")')
        ]
        fks = [
            ForeignKey(column=f["from"], references_table=f["table"], references_column=f["to"])
            for f in db.fetch_all(f'PRAGMA foreign_key_list("{table}")')
        ]
        return TableSchema(
            name=table,
            columns=columns,
            foreign_keys=fks,
            row_count=db.fetch_one(f'SELECT COUNT(*) AS n FROM "{table}"')["n"],
            sample_rows=db.fetch_all(f'SELECT * FROM "{table}" LIMIT 3'),
        )

    @mcp.tool(annotations=READ_ONLY)
    def run_query(
        sql: Annotated[str, Field(description="A single read-only SQLite SELECT / WITH statement")],
        limit: Annotated[int, Field(ge=1, le=1000, description="Maximum rows to return")] = 100,
    ) -> QueryResult:
        """Run a read-only SQL query against the database. Writes are rejected."""
        try:
            columns, rows, truncated = db.run_readonly(sql, limit)
        except QueryError as exc:
            raise ToolError(str(exc)) from exc
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)

    # ---------------------------------------------------------- domain-specific tools

    @mcp.tool(annotations=READ_ONLY)
    def search_products(
        query: Annotated[str | None, Field(description="Case-insensitive substring of the product name")] = None,
        category: Annotated[str | None, Field(description="Exact category, e.g. 'Electronics'")] = None,
        min_price: Annotated[float | None, Field(ge=0)] = None,
        max_price: Annotated[float | None, Field(ge=0)] = None,
        in_stock_only: bool = False,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> ProductSearchResult:
        """Search the product catalogue by name, category, price range and stock."""
        where, params = ["1=1"], {}
        if query:
            where.append("name LIKE :q")
            params["q"] = f"%{query}%"
        if category:
            where.append("category = :category COLLATE NOCASE")
            params["category"] = category
        if min_price is not None:
            where.append("price >= :min_price")
            params["min_price"] = min_price
        if max_price is not None:
            where.append("price <= :max_price")
            params["max_price"] = max_price
        if in_stock_only:
            where.append("stock > 0")
        clause = " AND ".join(where)

        total = db.fetch_one(f"SELECT COUNT(*) AS n FROM products WHERE {clause}", params)["n"]
        rows = db.fetch_all(
            f"SELECT id, name, category, price, stock FROM products WHERE {clause} ORDER BY name LIMIT :limit",
            {**params, "limit": limit},
        )
        return ProductSearchResult(products=[Product(**r) for r in rows], total_matches=total)

    @mcp.tool(annotations=READ_ONLY)
    def get_customer(
        customer_id: int | None = None,
        email: Annotated[str | None, Field(description="Exact email address")] = None,
        max_orders: Annotated[int, Field(ge=0, le=100, description="Most recent orders to include")] = 10,
    ) -> CustomerDetail:
        """Look up one customer by id or email, with lifetime value and recent orders."""
        if customer_id is None and not email:
            raise ToolError("Provide either customer_id or email.")
        if customer_id is not None:
            customer = db.fetch_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
        else:
            customer = db.fetch_one("SELECT * FROM customers WHERE email = ? COLLATE NOCASE", (email,))
        if customer is None:
            raise ToolError(f"No customer found for {'id ' + str(customer_id) if customer_id else email}.")

        order_rows = db.fetch_all(
            """
            SELECT o.id, o.order_date, o.status, ROUND(SUM(i.quantity * i.unit_price), 2) AS total
            FROM orders o JOIN order_items i ON i.order_id = o.id
            WHERE o.customer_id = ?
            GROUP BY o.id ORDER BY o.order_date DESC, o.id DESC
            """,
            (customer["id"],),
        )
        lifetime = round(sum(o["total"] for o in order_rows if o["status"] != "cancelled"), 2)

        orders = []
        for o in order_rows[:max_orders]:
            items = db.fetch_all(
                """
                SELECT i.product_id, p.name AS product_name, i.quantity, i.unit_price
                FROM order_items i JOIN products p ON p.id = i.product_id
                WHERE i.order_id = ? ORDER BY i.id
                """,
                (o["id"],),
            )
            orders.append(Order(**o, items=[OrderItem(**i) for i in items]))

        return CustomerDetail(**customer, lifetime_value=lifetime, orders=orders)

    @mcp.tool(annotations=READ_ONLY)
    def sales_summary(
        group_by: Literal["month", "category", "product"] = "month",
        start_date: Annotated[str | None, Field(pattern=ISO_DATE, description="Inclusive, YYYY-MM-DD")] = None,
        end_date: Annotated[str | None, Field(pattern=ISO_DATE, description="Inclusive, YYYY-MM-DD")] = None,
    ) -> SalesSummary:
        """Aggregate revenue, units and order counts (excluding cancelled orders)."""
        key_expr = {
            "month": "substr(o.order_date, 1, 7)",
            "category": "p.category",
            "product": "p.name",
        }[group_by]
        where, params = ["o.status != 'cancelled'"], {}
        if start_date:
            where.append("o.order_date >= :start")
            params["start"] = start_date
        if end_date:
            where.append("o.order_date <= :end")
            params["end"] = end_date

        rows = db.fetch_all(
            f"""
            SELECT {key_expr} AS key,
                   COUNT(DISTINCT o.id) AS orders,
                   SUM(i.quantity) AS units,
                   ROUND(SUM(i.quantity * i.unit_price), 2) AS revenue
            FROM orders o
            JOIN order_items i ON i.order_id = o.id
            JOIN products p ON p.id = i.product_id
            WHERE {" AND ".join(where)}
            GROUP BY key
            ORDER BY {"key" if group_by == "month" else "revenue DESC"}
            """,
            params,
        )
        buckets = [SalesBucket(**r) for r in rows]
        return SalesSummary(
            group_by=group_by,
            start_date=start_date,
            end_date=end_date,
            total_revenue=round(sum(b.revenue for b in buckets), 2),
            buckets=buckets,
        )

    # ------------------------------------------------------------ resources & prompts

    @mcp.resource("schema://database", name="database_schema", mime_type="text/plain")
    def database_schema() -> str:
        """The full CREATE statements for every table and index."""
        rows = db.fetch_all("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name")
        return ";\n\n".join(r["sql"] for r in rows) + ";"

    @mcp.prompt()
    def analyze_sales(period: str = "the last 6 months") -> str:
        """Ask the model to produce a short sales analysis using this server's tools."""
        return (
            f"Analyse store sales for {period}. Use sales_summary grouped by month, then by category, "
            "then by product. Report the trend, the top 3 products by revenue, and any category that is "
            "declining. Use search_products to flag top sellers that are out of stock."
        )

    return mcp
