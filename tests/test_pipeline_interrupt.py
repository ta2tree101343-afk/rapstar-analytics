import pytest

from collector.db import FetchRun, Post, make_engine, make_session_factory
from collector.pipeline import run_collection


CAPTION = "imag1ne\n#RAPSTAR2026"


def _item(mid: str, vc: int):
    return {
        "id": mid,
        "caption": CAPTION,
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "permalink": f"https://instagram.com/p/{mid}",
        "timestamp": "2026-09-15T12:34:56+0000",
        "view_count": vc,
        "like_count": 1,
        "comments_count": 0,
    }


def _kb_after(items):
    for it in items:
        yield it
    raise KeyboardInterrupt()


@pytest.fixture
def sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    return make_session_factory(engine)


def test_keyboard_interrupt_marks_run_as_interrupted(sf):
    with pytest.raises(KeyboardInterrupt):
        run_collection(sf, _kb_after([_item("A", 1), _item("B", 2)]))
    with sf() as s:
        run = s.query(FetchRun).one()
        assert run.status == "interrupted"
        assert run.finished_at is not None
        assert run.posts_seen == 2
        assert s.query(Post).count() == 2
