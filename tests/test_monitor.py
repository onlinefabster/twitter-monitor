"""Tests for the monitor worker's dedup + delivery flow (no network needed)."""

import pytest
from pathlib import Path

from skills import twitter_image_monitor as mon


async def _health_ok():
    return True


async def _scrape(user):
    return ["http://img/1"]


def _mk_fetch(payload, sig):
    async def _f(client, url):
        return (payload, sig)
    return _f


def _mk_archive(asset_id):
    async def _a(imm, u, url, p, s):
        return (asset_id, s + ".jpg")
    return _a


class FakeDB:
    """In-memory stand-in for twitter_db state used by _run_monitor."""

    def __init__(self):
        self.seen = set()
        self.sigs = set()
        self.seen_by_url = {}

    def is_seen(self, url):           return url in self.seen
    def mark_seen(self, url, u):      self.seen.add(url); self.seen_by_url[url] = u
    def is_signature_seen(self, s):   return s in self.sigs
    def mark_signature_seen(self, s, u, url=None): self.sigs.add(s)


@pytest.mark.asyncio
async def test_migrate_script_presence():
    # Guard against accidental removal of the migration tool at build time.
    assert Path(__file__).parents[1].joinpath("tools", "migrate_db.py").exists()


@pytest.mark.asyncio
async def test_filename_normalization():
    assert mon._normalize_image_url("http://x/a?name=small") == "http://x/a?name=large"
    assert mon._filename_from_url("http://x/a/b.jpeg") == "b.jpeg"


@pytest.mark.asyncio
async def test_signature_seen_skips_upload(monkeypatch):
    """An already-seen signature must not be uploaded; its URL still gets marked."""
    db = FakeDB()

    scraped = ["http://img/1"]
    calls = {"fetch": 0}

    monkeypatch.setattr(mon.twitter_db, "is_seen", db.is_seen)
    monkeypatch.setattr(mon.twitter_db, "mark_seen", db.mark_seen)
    monkeypatch.setattr(mon.twitter_db, "is_signature_seen", db.is_signature_seen)
    monkeypatch.setattr(mon.twitter_db, "mark_signature_seen", db.mark_signature_seen)
    monkeypatch.setattr(mon.twitter_db, "init_db", lambda: None)
    monkeypatch.setattr(mon.twitter_db, "list_watches", lambda: ["testuser"])
    monkeypatch.setattr(mon.web_agent_client, "health_check", _health_ok)
    monkeypatch.setattr(mon.web_agent_client, "scrape_twitter_media", _scrape)
    monkeypatch.setattr(mon, "_fetch_image_payload", _mk_fetch(b"img", "exists-sig"))
    monkeypatch.setattr(mon, "_archive_and_upload", _mk_archive(None))
    monkeypatch.setattr(mon.ImmichClient, "__init__", lambda self, **kw: None)

    db.sigs.add("exists-sig")  # signature already uploaded before

    summary, total = await mon._run_monitor()
    assert total == 0, "known signature must not be uploaded again"
    assert db.is_seen("http://img/1") is True, "URL must be marked so it isn't reprocessed"


@pytest.mark.asyncio
async def test_upload_success_marks_and_records(monkeypatch):
    db = FakeDB()

    monkeypatch.setattr(mon.twitter_db, "is_seen", db.is_seen)
    monkeypatch.setattr(mon.twitter_db, "mark_seen", db.mark_seen)
    monkeypatch.setattr(mon.twitter_db, "is_signature_seen", db.is_signature_seen)
    monkeypatch.setattr(mon.twitter_db, "mark_signature_seen", db.mark_signature_seen)
    monkeypatch.setattr(mon.twitter_db, "init_db", lambda: None)
    monkeypatch.setattr(mon.twitter_db, "list_watches", lambda: ["testuser"])
    monkeypatch.setattr(mon.web_agent_client, "health_check", _health_ok)
    monkeypatch.setattr(mon.web_agent_client, "scrape_twitter_media", _scrape)
    monkeypatch.setattr(mon, "_fetch_image_payload", _mk_fetch(b"img-bytes", "new-sig"))

    recorded = {}
    monkeypatch.setattr(mon.twitter_db, "record_upload",
                        lambda sig, u, url, fn, asset: recorded.__setitem__(sig, asset))
    monkeypatch.setattr(mon, "_archive_and_upload", _mk_archive("asset-1"))
    monkeypatch.setattr(mon.ImmichClient, "__init__", lambda self, **kw: None)

    summary, total = await mon._run_monitor()
    assert total == 1
    assert db.is_seen("http://img/1") is True
    assert db.is_signature_seen("new-sig") is True
    assert recorded.get("new-sig") == "asset-1"


@pytest.mark.asyncio
async def test_upload_failure_not_marked(monkeypatch):
    """If Immich upload fails, neither URL nor signature may be marked (retry next run)."""
    db = FakeDB()

    monkeypatch.setattr(mon.twitter_db, "is_seen", db.is_seen)
    monkeypatch.setattr(mon.twitter_db, "mark_seen", db.mark_seen)
    monkeypatch.setattr(mon.twitter_db, "is_signature_seen", db.is_signature_seen)
    monkeypatch.setattr(mon.twitter_db, "mark_signature_seen", db.mark_signature_seen)
    monkeypatch.setattr(mon.twitter_db, "init_db", lambda: None)
    monkeypatch.setattr(mon.twitter_db, "list_watches", lambda: ["testuser"])
    monkeypatch.setattr(mon.web_agent_client, "health_check", _health_ok)
    monkeypatch.setattr(mon.web_agent_client, "scrape_twitter_media", _scrape)
    monkeypatch.setattr(mon, "_fetch_image_payload", _mk_fetch(b"img", "sig-fail"))
    monkeypatch.setattr(mon, "_archive_and_upload", _mk_archive(None))
    monkeypatch.setattr(mon.ImmichClient, "__init__", lambda self, **kw: None)

    summary, total = await mon._run_monitor()
    assert total == 0
    assert db.is_seen("http://img/1") is False, "must retry failed uploads"
    assert db.is_signature_seen("sig-fail") is False