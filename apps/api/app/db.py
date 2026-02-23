from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://autonoma:autonoma_dev@postgres:5432/autonoma",
    )


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(_database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory():
    return sessionmaker(bind=get_engine(), class_=Session, expire_on_commit=False)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    if os.getenv("DB_AUTO_CREATE", "false").lower() != "true":
        return
    from . import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(engine)


def reset_db_cache() -> None:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
