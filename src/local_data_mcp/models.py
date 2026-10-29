"""Pydantic models that define the structured output of each tool.

MCPServer turns these into each tool's `outputSchema`, and the values the
tools return are sent to the client as `structuredContent`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TableInfo(BaseModel):
    name: str
    row_count: int


class TableList(BaseModel):
    tables: list[TableInfo]


class ColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    default: str | None = None


class ForeignKey(BaseModel):
    column: str
    references_table: str
    references_column: str


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKey]
    row_count: int
    sample_rows: list[dict[str, Any]] = Field(description="Up to 3 example rows")


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = Field(description="True if more rows existed than the limit")


class Product(BaseModel):
    id: int
    name: str
    category: str
    price: float
    stock: int


class ProductSearchResult(BaseModel):
    products: list[Product]
    total_matches: int


class OrderItem(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: float


class Order(BaseModel):
    id: int
    order_date: str
    status: str
    total: float
    items: list[OrderItem]


class CustomerDetail(BaseModel):
    id: int
    name: str
    email: str
    city: str
    joined: str
    lifetime_value: float = Field(description="Sum of all non-cancelled order totals")
    orders: list[Order]


class SalesBucket(BaseModel):
    key: str = Field(description="The month (YYYY-MM), category or product name")
    orders: int
    units: int
    revenue: float


class SalesSummary(BaseModel):
    group_by: str
    start_date: str | None
    end_date: str | None
    total_revenue: float
    buckets: list[SalesBucket]
