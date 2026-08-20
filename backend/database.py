from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from models import (  # noqa: F401
        Booking,
        FeePolicy,
        ParkingHistory,
        ParkingSlot,
        ParkingSpace,
        User,
    )

    Base.metadata.create_all(bind=engine)
    _migrate_bookings_nullable_lot()


def _migrate_bookings_nullable_lot() -> None:
    """SQLite: rebuild bookings if lot/slot_id were created NOT NULL."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(bookings)").fetchall()
        if not rows:
            return
        cols = {r[1]: r for r in rows}  # name -> row
        lot_notnull = cols.get("lot") and cols["lot"][3] == 1
        slot_notnull = cols.get("slot_id") and cols["slot_id"][3] == 1
        if not lot_notnull and not slot_notnull:
            return
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS bookings_new (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                slot_id VARCHAR(36),
                vehicle_number VARCHAR(15) NOT NULL,
                category VARCHAR(2) NOT NULL,
                level INTEGER NOT NULL,
                lot VARCHAR(32),
                start_at DATETIME NOT NULL,
                end_at DATETIME NOT NULL,
                status VARCHAR(16) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users (id),
                FOREIGN KEY(slot_id) REFERENCES parking_slots (id)
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO bookings_new
            (id, user_id, slot_id, vehicle_number, category, level, lot, start_at, end_at, status, created_at)
            SELECT id, user_id, slot_id, vehicle_number, category, level, lot, start_at, end_at, status, created_at
            FROM bookings
            """
        )
        conn.exec_driver_sql("DROP TABLE bookings")
        conn.exec_driver_sql("ALTER TABLE bookings_new RENAME TO bookings")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_bookings_user_id ON bookings (user_id)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_bookings_vehicle_number ON bookings (vehicle_number)"
        )
