import os
import pytest

from services import twitter_db


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "twitter-monitor.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    twitter_db.DB_PATH = db_file
    twitter_db.init_db()
    yield


def test_watch_roundtrip():
    assert twitter_db.add_watch("FooBar") is True
    assert twitter_db.add_watch("FooBar") is False  # duplicate
    assert twitter_db.list_watches() == ["foobar"]  # lowercased


def test_remove_watch():
    twitter_db.add_watch("bar")
    assert twitter_db.remove_watch("bAr") is True
    assert twitter_db.remove_watch("bar") is False


def test_seen_and_signature_dedup():
    twitter_db.mark_seen("http://img/1", "foo")
    assert twitter_db.is_seen("http://img/1") is True
    assert twitter_db.is_seen("http://img/2") is False

    twitter_db.mark_signature_seen("aaabbb", "foo", "http://img/1")
    assert twitter_db.is_signature_seen("aaabbb") is True
    assert twitter_db.is_signature_seen("ccc") is False


def test_upload_records():
    twitter_db.record_upload("sig1", "foo", "http://img/1", "sig1.jpg", "asset1")
    twitter_db.record_upload("sig1", "foo", "http://img/1", "sig1.jpg", "asset1")  # dup ignored
    recs = twitter_db.list_uploads(username="foo")
    assert len(recs) == 1
    assert recs[0]["immich_asset_id"] == "asset1"
    assert twitter_db.upload_count("foo") == 1


def test_run_history():
    run_id = twitter_db.record_run_start()
    twitter_db.record_run_finish(run_id, "ok", "summary text")
    runs = twitter_db.last_run(10)
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"