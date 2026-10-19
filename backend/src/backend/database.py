from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    password = settings.db_password.get_secret_value()

    if not password:
        raise ValueError("DB_PASSWORD must be set before connecting to PostgreSQL.")

    url = URL.create(
        drivername="postgresql+psycopg",
        username=settings.db_user,
        password=password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )

    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )


@lru_cache(maxsize=1)
def get_database_engine() -> Engine:
    return create_database_engine(Settings())


def get_db_session() -> Iterator[Session]:
    with Session(get_database_engine()) as session:
        yield session
