from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TableResponse(BaseModel):
    id: UUID
    schema_name: str
    table_name: str
    table_type: str
    comment: str | None
    row_count_estimate: int | None
    column_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ColumnResponse(BaseModel):
    id: UUID
    column_name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    default_value: str | None
    comment: str | None
    ordinal_position: int

    model_config = {"from_attributes": True}


class RelationshipResponse(BaseModel):
    id: UUID | None = None
    constraint_name: str | None
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    is_manual: bool = False
    relationship_type: str | None = None


class RelationshipCreate(BaseModel):
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    constraint_name: str | None = None
    relationship_type: str | None = None


class TableDetailResponse(BaseModel):
    id: UUID
    schema_name: str
    table_name: str
    table_type: str
    comment: str | None
    row_count_estimate: int | None
    columns: list[ColumnResponse]
    outgoing_relationships: list[RelationshipResponse]
    incoming_relationships: list[RelationshipResponse]

    model_config = {"from_attributes": True}


class IntrospectionResult(BaseModel):
    tables_found: int
    columns_found: int
    relationships_found: int


class AvailableTableEntry(BaseModel):
    """A single table entry returned by the available-tables endpoint.

    Represents a dbo table that has passed auto-exclusion rules and is
    eligible to be added to the connection's whitelist.
    """

    schema_name: str
    table_name: str
