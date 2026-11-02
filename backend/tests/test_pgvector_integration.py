"""Opt-in smoke test against a PostgreSQL server with pgvector enabled."""

import os

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select


def test_postgresql_pgvector_cosine_search():
    database_url = os.getenv("TEST_POSTGRESQL_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRESQL_URL is not configured")

    engine = create_engine(database_url)
    metadata = MetaData()
    vectors = Table(
        "test_chunk_vectors",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("embedding", Vector(3), nullable=False),
        prefixes=["TEMPORARY"],
    )
    try:
        with engine.begin() as connection:
            vectors.create(connection)
            connection.execute(
                vectors.insert(),
                [
                    {"id": 1, "embedding": [1.0, 0.0, 0.0]},
                    {"id": 2, "embedding": [0.0, 1.0, 0.0]},
                ],
            )
            nearest = connection.scalar(
                select(vectors.c.id)
                .order_by(vectors.c.embedding.cosine_distance([0.9, 0.1, 0.0]))
                .limit(1)
            )
    finally:
        engine.dispose()

    assert nearest == 1
