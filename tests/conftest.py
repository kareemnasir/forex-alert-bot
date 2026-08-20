import hashlib
import stat
from pathlib import Path

import pytest

RUNTIME_DATABASE = Path(__file__).parents[1] / "data" / "forex-alert-bot.sqlite3"


def _database_snapshot() -> dict[Path, tuple[int, int, int, int, int, str] | None]:
    snapshots = {}
    for path in (
        RUNTIME_DATABASE,
        Path(f"{RUNTIME_DATABASE}-wal"),
        Path(f"{RUNTIME_DATABASE}-shm"),
    ):
        if not path.exists():
            snapshots[path] = None
            continue
        metadata = path.stat()
        snapshots[path] = (
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_ino,
            stat.S_IMODE(metadata.st_mode),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return snapshots


@pytest.fixture(scope="session", autouse=True)
def preserve_runtime_database():
    """Prove the complete test session leaves runtime SQLite files untouched."""
    before = _database_snapshot()

    yield

    assert _database_snapshot() == before, (
        "The test suite created or modified the default runtime SQLite database. "
        "Inject a tmp_path database into every SQLite or pipeline test."
    )
