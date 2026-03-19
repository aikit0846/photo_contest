import sqlite3
from collections.abc import Generator

from sqlalchemy import Engine, event
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        with engine.begin() as connection:
            guest_columns = connection.exec_driver_sql("PRAGMA table_info(guests)").fetchall()
            guest_column_names = {column[1] for column in guest_columns}
            if "side" not in guest_column_names:
                connection.exec_driver_sql(
                    "ALTER TABLE guests ADD COLUMN side VARCHAR(20) DEFAULT 'groom' NOT NULL",
                )
            event_columns = connection.exec_driver_sql("PRAGMA table_info(events)").fetchall()
            event_column_names = {column[1] for column in event_columns}
            if "feedback_released" not in event_column_names:
                connection.exec_driver_sql(
                    "ALTER TABLE events ADD COLUMN feedback_released BOOLEAN DEFAULT 0 NOT NULL",
                )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
