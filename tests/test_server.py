import sqlite3
import sys

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {"list_tables", "describe_table", "run_query", "search_products", "get_customer", "sales_summary"}


async def test_tools_advertise_output_schemas(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == EXPECTED_TOOLS
    for tool in tools.values():
        assert tool.output_schema is not None, tool.name
        assert tool.annotations.read_only_hint is True


async def test_list_tables(server):
    async with Client(server) as client:
        result = await client.call_tool("list_tables")
    names = {t["name"]: t["row_count"] for t in result.structured_content["tables"]}
    assert names["products"] == 15
    assert names["customers"] == 40
    assert names["orders"] == 300


async def test_describe_table_and_unknown_table(server):
    async with Client(server) as client:
        ok = await client.call_tool("describe_table", {"table": "orders"})
        bad = await client.call_tool("describe_table", {"table": "orders; DROP TABLE orders"})
    fks = ok.structured_content["foreign_keys"]
    assert {"column": "customer_id", "references_table": "customers", "references_column": "id"} in fks
    assert len(ok.structured_content["sample_rows"]) == 3
    assert bad.is_error and "Unknown table" in bad.content[0].text


async def test_search_products_filters(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "search_products", {"category": "electronics", "max_price": 100, "limit": 50}
        )
    products = result.structured_content["products"]
    assert products and all(p["category"] == "Electronics" and p["price"] <= 100 for p in products)
    assert result.structured_content["total_matches"] == len(products)


async def test_get_customer_by_email_and_missing(server):
    async with Client(server) as client:
        by_id = await client.call_tool("get_customer", {"customer_id": 1})
        email = by_id.structured_content["email"]
        by_email = await client.call_tool("get_customer", {"email": email.upper()})
        missing = await client.call_tool("get_customer", {"customer_id": 99999})
        neither = await client.call_tool("get_customer", {})
    assert by_email.structured_content["id"] == 1
    assert missing.is_error and neither.is_error


async def test_sales_summary_totals_agree(server):
    async with Client(server) as client:
        by_month = await client.call_tool("sales_summary", {"group_by": "month"})
        by_cat = await client.call_tool("sales_summary", {"group_by": "category"})
        q = await client.call_tool(
            "run_query",
            {
                "sql": "SELECT ROUND(SUM(quantity*unit_price),2) AS r FROM order_items i "
                "JOIN orders o ON o.id=i.order_id WHERE o.status != 'cancelled'"
            },
        )
    expected = q.structured_content["rows"][0]["r"]
    assert by_month.structured_content["total_revenue"] == pytest.approx(expected)
    assert by_cat.structured_content["total_revenue"] == pytest.approx(expected)


async def test_sales_summary_rejects_bad_date(server):
    async with Client(server) as client:
        result = await client.call_tool("sales_summary", {"start_date": "last week"})
    assert result.is_error


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT 1; DROP TABLE orders",
        "WITH x AS (SELECT 1) DELETE FROM orders",
        "WITH x AS (SELECT 1) INSERT INTO products (name, category, price, stock) VALUES ('x','y',1,1)",
        "SELECT * FROM pragma_writable_schema",
        "ATTACH DATABASE ':memory:' AS evil",
    ],
)
async def test_run_query_is_read_only(server, db_path, sql):
    async with Client(server) as client:
        result = await client.call_tool("run_query", {"sql": sql})
    assert result.is_error, sql
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 300
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 15


async def test_run_query_truncates(server):
    async with Client(server) as client:
        result = await client.call_tool("run_query", {"sql": "SELECT * FROM orders", "limit": 5})
    assert result.structured_content["row_count"] == 5
    assert result.structured_content["truncated"] is True


async def test_schema_resource_and_prompt(server):
    async with Client(server) as client:
        schema = await client.read_resource("schema://database")
        prompt = await client.get_prompt("analyze_sales", {"period": "2025"})
    assert "CREATE TABLE orders" in schema.contents[0].text
    assert "2025" in prompt.messages[0].content.text


async def test_end_to_end_over_stdio(db_path):
    """Launch the real console entry point as a subprocess, exactly as a client would."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "local_data_mcp", "--db", str(db_path)]
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        result = await client.call_tool("search_products", {"query": "chair"})
    assert {t.name for t in tools.tools} == EXPECTED_TOOLS
    assert result.structured_content["products"][0]["name"] == "Ergonomic Chair"
