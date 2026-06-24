"""Tests for the SRC data layer (enriched schema). Each test runs against a
fresh in-memory database — no shared state, no network."""

import pytest

import db


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    db.seed(c)
    yield c
    c.close()


# --- Seed + reads ----------------------------------------------------------

def test_seed_is_idempotent(conn):
    before = conn.execute("SELECT COUNT(*) AS n FROM matches").fetchone()["n"]
    db.seed(conn)
    after = conn.execute("SELECT COUNT(*) AS n FROM matches").fetchone()["n"]
    assert before == after == 14


def test_kpis(conn):
    k = db.kpis(conn)
    assert k["pendingMatches"] == 9
    assert k["openDisputes"] == 2
    assert k["assetsManaged"] == 8
    assert 0 <= k["matchRate"] <= 100
    assert k["revenueAtRisk"] > 0 and k["catalogRevenue"] > 0
    # Goal-aligned metrics: unresolved backlog = pending + disputed
    assert k["openBacklog"] == k["pendingMatches"] + 2 == 11
    assert 0 <= k["resolutionRate"] <= 100
    assert k["pastWindow"] == 0  # nothing seeded older than the 7-day window
    assert k["oldestPendingDays"] >= 0
    assert "revenueRecovered" not in k


def test_weekly_burndown(conn):
    w = db.weekly(conn)
    assert len(w) == 12
    assert all({"week", "detected", "resolved", "backlog"} <= set(r) for r in w)
    # Resolution outpaces detection, so the backlog burns down across the window
    assert w[-1]["backlog"] < w[0]["backlog"]
    assert all(r["backlog"] >= 0 for r in w)


def test_match_counts(conn):
    c = db.match_counts(conn)
    assert c["all"] == 14 == c["pending"] + c["cleared"] + c["rejected"] + c["disputed"]
    assert c["pending"] == 9


def test_list_matches_pagination(conn):
    rows, total = db.list_matches(conn, page=1, page_size=10)
    assert total == 14 and len(rows) == 10
    rows2, _ = db.list_matches(conn, page=2, page_size=10)
    assert len(rows2) == 4


def test_list_matches_status_filter(conn):
    rows, total = db.list_matches(conn, status="pending", page_size=50)
    assert total == 9 and all(m["status"] == "pending" for m in rows)


def test_list_matches_search(conn):
    rows, total = db.list_matches(conn, q="cobalt", page_size=50)
    assert total >= 1 and all("cobalt" in (m["upload_title"] + m["asset_title"]).lower() for m in rows)


def test_get_match_joins_asset(conn):
    m = db.get_match(conn, 1)
    assert m["asset_title"] and m["asset_isrc"] and "asset_ownership" in m


# --- Match actions ---------------------------------------------------------

def test_approve_and_reject(conn):
    assert db.apply_match_action(conn, 1, "approve")["status"] == "cleared"
    assert db.apply_match_action(conn, 2, "reject")["status"] == "rejected"


def test_dispute_creates_open_case(conn):
    before = db.kpis(conn)["openDisputes"]
    db.apply_match_action(conn, 1, "dispute")
    assert db.kpis(conn)["openDisputes"] == before + 1


def test_unknown_action_raises(conn):
    with pytest.raises(ValueError):
        db.apply_match_action(conn, 1, "nuke")


def test_bulk_only_pending(conn):
    pending = [m["id"] for m in db.list_matches(conn, status="pending", page_size=50)[0]]
    cleared = [m["id"] for m in db.list_matches(conn, status="cleared", page_size=50)[0]]
    changed = db.bulk_match_action(conn, pending + cleared, "approve")
    assert set(changed) == set(pending)
    assert db.kpis(conn)["pendingMatches"] == 0


def test_bulk_rejects_unknown_action(conn):
    with pytest.raises(ValueError):
        db.bulk_match_action(conn, [1], "dispute")


# --- Disputes --------------------------------------------------------------

def test_get_dispute_joins(conn):
    d = db.get_dispute(conn, 1)
    assert d["case_ref"] and d["asset_title"] and d["respondent"]


def test_resolve_upheld_clears_match(conn):
    d = db.get_dispute(conn, 1)
    db.resolve_dispute(conn, 1, "upheld")
    assert db.get_match(conn, d["match_id"])["status"] == "cleared"


def test_resolve_withdrawn_rejects_match(conn):
    d = db.get_dispute(conn, 2)
    db.resolve_dispute(conn, 2, "withdrawn")
    assert db.get_match(conn, d["match_id"])["status"] == "rejected"


def test_unknown_resolution_raises(conn):
    with pytest.raises(ValueError):
        db.resolve_dispute(conn, 1, "shrug")


# --- Policies --------------------------------------------------------------

def test_policy_toggle_and_threshold(conn):
    p = db.list_policies(conn)[0]
    db.set_policy(conn, p["id"], enabled=not bool(p["enabled"]))
    assert bool(db.list_policies(conn)[0]["enabled"]) != bool(p["enabled"])
    db.set_policy(conn, p["id"], threshold=88)
    assert db.list_policies(conn)[0]["threshold"] == 88


# --- Catalog ---------------------------------------------------------------

def test_create_asset_assigns_isrc(conn):
    a = db.create_asset(conn, "New Single", "Halcyon", "audio", 184)
    assert a["isrc"].startswith("ZZMMG26")
    assert db.kpis(conn)["assetsManaged"] == 9


def test_create_asset_validates(conn):
    with pytest.raises(ValueError):
        db.create_asset(conn, "", "A", "audio", 100)
    with pytest.raises(ValueError):
        db.create_asset(conn, "T", "A", "hologram", 100)
    with pytest.raises(ValueError):
        db.create_asset(conn, "T", "A", "audio", 999)


def test_list_assets_pagination_and_claims(conn):
    rows, total = db.list_assets(conn, page_size=5)
    assert total == 8 and len(rows) == 5 and "claims" in rows[0]


# --- Analytics -------------------------------------------------------------

def test_content_type_breakdown(conn):
    bd = db.content_type_breakdown(conn)
    assert bd and sum(c["n"] for c in bd) == 14


def test_top_works(conn):
    top = db.top_works(conn, limit=3)
    assert len(top) == 3 and top[0]["claims"] >= top[-1]["claims"]


# --- Respondent flow -------------------------------------------------------

def test_respondent_license_opens_dispute(conn):
    before = db.kpis(conn)["openDisputes"]
    out = db.respondent_submit(conn, 1, "license")
    assert out["status"] == "disputed"
    assert db.get_match(conn, 1)["status"] == "disputed"
    assert db.kpis(conn)["openDisputes"] == before + 1


def test_respondent_unpublish_clears_match(conn):
    out = db.respondent_submit(conn, 1, "unpublish")
    assert out["status"] == "cleared"
    assert db.get_match(conn, 1)["status"] == "cleared"


def test_respondent_invalid_choice_raises(conn):
    with pytest.raises(ValueError):
        db.respondent_submit(conn, 1, "")


def test_actions_are_logged(conn):
    before = len(db.list_activity(conn, limit=100))
    db.apply_match_action(conn, 1, "approve")
    assert len(db.list_activity(conn, limit=100)) == before + 1
