import copy
import json
from pathlib import Path

import pytest

DIR_FIXTURE = Path(__file__).parent / "fixtures" / "events"


def muat_fixture(tipe: str) -> dict:
    for b in sorted(DIR_FIXTURE.glob("*.json")):
        d = json.loads(b.read_text(encoding="utf-8"))
        if d["event_type"] == tipe:
            return copy.deepcopy(d)
    raise AssertionError(tipe)


@pytest.fixture
def event_stok() -> dict:
    return muat_fixture("stok.berubah")
