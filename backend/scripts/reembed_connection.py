#!/usr/bin/env python3
"""
Re-generate missing embeddings for all semantic metadata of a connection.

Processes each entity type (tables, columns, glossary terms, metrics,
sample queries, knowledge chunks) in its own transaction so partial
progress is never lost on interruption.

Usage:
    # From repo root:
    python backend/scripts/reembed_connection.py [connection_id]

    # Default connection ID can be set via CONNECTION_ID env var.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# ── Load .env from repo root ──────────────────────────────────────────────────
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            _val = _val.split("#")[0].strip()  # strip inline comments
            os.environ.setdefault(_key.strip(), _val)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models.glossary import GlossaryTerm  # noqa: E402
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.db.models.metric import MetricDefinition  # noqa: E402
from app.db.models.sample_query import SampleQuery  # noqa: E402
from app.db.models.schema_cache import CachedColumn, CachedTable  # noqa: E402
from app.services.embedding_service import (  # noqa: E402
    embed_column,
    embed_glossary_term,
    embed_knowledge_chunk,
    embed_metric,
    embed_sample_query,
    embed_table,
)


async def embed_entity(label: str, items, embed_fn, assign_fn) -> int:
    """Embed a list of items and return the count embedded."""
    count = 0
    for item in items:
        embedding = await embed_fn(item)
        assign_fn(item, embedding)
        count += 1
        if count % 20 == 0:
            print(f"  [{label}] {count}/{len(items)} ...", flush=True)
    return count


async def main(connection_id: str) -> None:
    conn_uuid = uuid.UUID(connection_id)
    db_url = os.environ["DATABASE_URL"]

    engine = create_async_engine(db_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total = 0

    print(f"connection : {connection_id}", flush=True)
    print(f"database   : {db_url.split('@')[-1]}", flush=True)
    print(flush=True)

    # ── 1. Tables ─────────────────────────────────────────────────────────────
    async with Session() as session:
        result = await session.execute(
            select(CachedTable).where(
                CachedTable.connection_id == conn_uuid,
                CachedTable.description_embedding.is_(None),
            )
        )
        tables = result.scalars().all()
        print(f"[tables] {len(tables)} missing embeddings", flush=True)
        n = await embed_entity(
            "tables", tables,
            embed_fn=embed_table,
            assign_fn=lambda t, e: setattr(t, "description_embedding", e),
        )
        await session.commit()
        total += n
        print(f"[tables] committed {n}", flush=True)

    # ── 2. Columns ────────────────────────────────────────────────────────────
    async with Session() as session:
        result = await session.execute(
            select(CachedColumn)
            .join(CachedTable, CachedColumn.table_id == CachedTable.id)
            .where(
                CachedTable.connection_id == conn_uuid,
                CachedColumn.description_embedding.is_(None),
            )
        )
        columns = result.scalars().all()
        print(f"\n[columns] {len(columns)} missing embeddings", flush=True)

        # Need table_name for each column — load table names in bulk
        table_ids = list({c.table_id for c in columns})
        tbl_result = await session.execute(
            select(CachedTable.id, CachedTable.table_name).where(
                CachedTable.id.in_(table_ids)
            )
        )
        table_name_map: dict = {row.id: row.table_name for row in tbl_result}

        count = 0
        for col in columns:
            tname = table_name_map.get(col.table_id, "unknown")
            col.description_embedding = await embed_column(col, tname)
            count += 1
            if count % 20 == 0:
                print(f"  [columns] {count}/{len(columns)} ...", flush=True)
        await session.commit()
        total += count
        print(f"[columns] committed {count}", flush=True)

    # ── 3. Glossary terms ─────────────────────────────────────────────────────
    async with Session() as session:
        result = await session.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.connection_id == conn_uuid,
                GlossaryTerm.term_embedding.is_(None),
            )
        )
        terms = result.scalars().all()
        print(f"\n[glossary] {len(terms)} missing embeddings", flush=True)
        n = await embed_entity(
            "glossary", terms,
            embed_fn=embed_glossary_term,
            assign_fn=lambda t, e: setattr(t, "term_embedding", e),
        )
        await session.commit()
        total += n
        print(f"[glossary] committed {n}", flush=True)

    # ── 4. Metrics ────────────────────────────────────────────────────────────
    async with Session() as session:
        result = await session.execute(
            select(MetricDefinition).where(
                MetricDefinition.connection_id == conn_uuid,
                MetricDefinition.metric_embedding.is_(None),
            )
        )
        metrics = result.scalars().all()
        print(f"\n[metrics] {len(metrics)} missing embeddings", flush=True)
        n = await embed_entity(
            "metrics", metrics,
            embed_fn=embed_metric,
            assign_fn=lambda m, e: setattr(m, "metric_embedding", e),
        )
        await session.commit()
        total += n
        print(f"[metrics] committed {n}", flush=True)

    # ── 5. Sample queries ─────────────────────────────────────────────────────
    async with Session() as session:
        result = await session.execute(
            select(SampleQuery).where(
                SampleQuery.connection_id == conn_uuid,
                SampleQuery.question_embedding.is_(None),
            )
        )
        queries = result.scalars().all()
        print(f"\n[sample_queries] {len(queries)} missing embeddings", flush=True)
        n = await embed_entity(
            "sample_queries", queries,
            embed_fn=embed_sample_query,
            assign_fn=lambda q, e: setattr(q, "question_embedding", e),
        )
        await session.commit()
        total += n
        print(f"[sample_queries] committed {n}", flush=True)

    # ── 6. Knowledge chunks ───────────────────────────────────────────────────
    async with Session() as session:
        result = await session.execute(
            select(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.connection_id == conn_uuid,
                KnowledgeChunk.chunk_embedding.is_(None),
            )
        )
        chunks = result.scalars().all()
        print(f"\n[knowledge] {len(chunks)} missing embeddings", flush=True)
        n = await embed_entity(
            "knowledge", chunks,
            embed_fn=embed_knowledge_chunk,
            assign_fn=lambda c, e: setattr(c, "chunk_embedding", e),
        )
        await session.commit()
        total += n
        print(f"[knowledge] committed {n}", flush=True)

    await engine.dispose()
    print(f"\nDone. {total} items embedded total.", flush=True)


if __name__ == "__main__":
    _connection_id = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("CONNECTION_ID", "3803127e-a803-4d72-b7cb-5853a7045505")
    )
    asyncio.run(main(_connection_id))
