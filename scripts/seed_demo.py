from app.config import get_settings
from app.database import init_db
from app.repositories import get_repository
from app.services.contest import create_guest
from app.services.contest import get_event
from app.storage import get_storage


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
    storage = get_storage()
    storage.ensure_ready()
    if settings.data_backend.lower() == "sqlite":
        init_db()
    repository = get_repository()
    get_event(repository, settings)
    for name, table_name, group_type, eligible in SAMPLE_GUESTS:
        create_guest(
            repository,
            name=name,
            table_name=table_name,
            group_type=group_type,
            eligible=eligible,
        )
    print("Demo guests created.")


if __name__ == "__main__":
    main()
