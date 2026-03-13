from app.config import get_settings
from app.database import SessionLocal
from app.database import init_db
from app.services.contest import create_guest
from app.services.contest import ensure_default_event
from app.services.contest import ensure_storage


SAMPLE_GUESTS = [
    ("新郎友人A", "A卓", "friend", True),
    ("新郎友人B", "A卓", "friend", True),
    ("新婦友人A", "B卓", "friend", True),
    ("新婦友人B", "B卓", "friend", True),
    ("叔母", "親族卓", "family", False),
    ("従兄弟", "親族卓", "family", False),
]


def main() -> None:
    settings = get_settings()
    ensure_storage(settings)
    init_db()
    with SessionLocal() as session:
        ensure_default_event(session, settings)
        for name, table_name, group_type, eligible in SAMPLE_GUESTS:
            create_guest(
                session,
                name=name,
                table_name=table_name,
                group_type=group_type,
                eligible=eligible,
            )
    print("Demo guests created.")


if __name__ == "__main__":
    main()
