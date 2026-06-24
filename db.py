"""SQLite data layer for the Spotify Rights Center (SRC) simulation.

Self-contained, functional rights-management backend with professionally-shaped
data: reference works (ISRC/ISWC, rights splits, territories, revenue), detected
matches (content type, confidence, monthly streams, revenue impact, claim type,
reviewer), dispute cases (claimant/respondent, priority, SLA), and enforcement
policies. Seeded fictional data — NOT real Spotify data (the public Web API has
no rights endpoints). Actions persist.

Server-side list functions support filtering, sorting, and pagination so each
page can render a real slice from a URL.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import string
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("SRC_DB_PATH", os.path.join(os.path.dirname(__file__), "src.db"))

MATCH_STATUSES = ("pending", "cleared", "rejected", "disputed")
ACTION_TO_STATUS = {"approve": "cleared", "reject": "rejected", "dispute": "disputed"}
DISPUTE_RESOLUTIONS = {"upheld": "cleared", "withdrawn": "rejected"}

MATCH_SORTS = {
    "confidence": "m.match_pct", "revenue": "m.revenue_cents",
    "streams": "m.monthly_streams", "detected": "m.detected_at",
}
ASSET_SORTS = {
    "title": "a.title", "isrc": "a.isrc", "revenue": "a.revenue_cents",
    "claims": "claims", "released": "a.release_date",
}


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_B62 = string.ascii_letters + string.digits


def spotify_id(seed: str) -> str:
    """Deterministic, fake 22-char base62 Spotify track id derived from a seed
    (e.g., ISRC). Looks real; isn't. Used to build open.spotify.com links."""
    n = int.from_bytes(hashlib.sha1(seed.encode()).digest(), "big")
    out = []
    for _ in range(22):
        n, r = divmod(n, 62)
        out.append(_B62[r])
    return "".join(out)


def _row(r: sqlite3.Row) -> dict:
    return dict(r)


# --- Schema ---------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS rightsholders (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY,
    rightsholder_id INTEGER NOT NULL REFERENCES rightsholders(id),
    title TEXT NOT NULL, artist TEXT NOT NULL,
    isrc TEXT NOT NULL, iswc TEXT, spotify_id TEXT,
    label TEXT, kind TEXT NOT NULL, markets INTEGER NOT NULL,
    ownership_pct INTEGER NOT NULL, rights_type TEXT NOT NULL,
    release_date TEXT, revenue_cents INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    upload_title TEXT NOT NULL, uploader TEXT NOT NULL,
    content_type TEXT NOT NULL, source TEXT NOT NULL,
    match_pct INTEGER NOT NULL, kind TEXT NOT NULL, markets INTEGER NOT NULL,
    monthly_streams INTEGER NOT NULL DEFAULT 0,
    revenue_cents INTEGER NOT NULL DEFAULT 0,
    claim_type TEXT NOT NULL, reviewer TEXT,
    segment TEXT, status TEXT NOT NULL, detected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY, case_ref TEXT NOT NULL,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    claimant TEXT NOT NULL, respondent TEXT NOT NULL,
    reason TEXT NOT NULL, priority TEXT NOT NULL,
    status TEXT NOT NULL, resolution TEXT, assigned_to TEXT,
    opened_at TEXT NOT NULL, sla_deadline TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY,
    rightsholder_id INTEGER NOT NULL REFERENCES rightsholders(id),
    label TEXT NOT NULL, descr TEXT NOT NULL,
    scope TEXT NOT NULL, action TEXT NOT NULL, territories TEXT NOT NULL,
    priority INTEGER NOT NULL, enabled INTEGER NOT NULL, threshold INTEGER
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL,
    action TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_stats (
    id INTEGER PRIMARY KEY, week TEXT NOT NULL,
    detected INTEGER NOT NULL, resolved INTEGER NOT NULL
);
"""

# Open backlog (unresolved matches) entering the 12-week window. The weekly
# detected/resolved flows burn this down — it is the number the operation
# drives toward zero. Seeded history; see weekly().
WEEKLY_BACKLOG_START = 60


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def is_seeded(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) AS n FROM rightsholders").fetchone()["n"] > 0


def log(conn: sqlite3.Connection, actor: str, action: str, detail: str) -> None:
    conn.execute("INSERT INTO activity (ts, actor, action, detail) VALUES (?, ?, ?, ?)",
                 (_now(), actor, action, detail))


# --- Seed -----------------------------------------------------------------

def seed(conn: sqlite3.Connection) -> None:
    if is_seeded(conn):
        return
    now = datetime.now(timezone.utc)
    d = lambda days: (now - timedelta(days=days)).date().isoformat()

    conn.execute("INSERT INTO rightsholders (id, name, kind) VALUES (1, ?, ?)",
                 ("Meridian Music Group", "label"))

    # (title, artist, isrc, iswc, label, kind, markets, ownership, rights_type, release_days, revenue_cents)
    assets = [
        ("Midnight Reprise", "Halcyon", "ZZMMG2600101", "T-916.241.001-2", "Meridian", "audio", 184, 100, "Master + Publishing", 420, 4820000),
        ("Golden Hour", "Halcyon", "ZZMMG2600102", "T-916.241.002-9", "Meridian", "audio", 92, 100, "Master", 380, 1240000),
        ("Paper Planes (Live)", "The Lon", "ZZMMG2600133", "T-742.118.067-3", "Meridian / Co-pub", "audio", 178, 65, "Publishing", 300, 2655000),
        ("Static Bloom", "Nova Kin", "ZZMMG2600150", None, "Meridian", "video", 64, 100, "Master", 210, 980000),
        ("Lowlight", "Halcyon", "ZZMMG2600161", "T-916.241.061-4", "Meridian", "audio", 120, 80, "Master + Publishing", 150, 3110000),
        ("Cobalt", "Nova Kin", "ZZMMG2600177", "T-559.902.177-1", "Meridian", "audio", 184, 100, "Master", 95, 5240000),
        ("Northern Wires", "The Lon", "ZZMMG2600188", "T-742.118.088-0", "Co-pub", "audio", 40, 50, "Publishing", 60, 410000),
        ("Afterglow (Edit)", "Halcyon", "ZZMMG2600190", "T-916.241.090-7", "Meridian", "audio", 184, 100, "Master + Publishing", 30, 1875000),
    ]
    for i, a in enumerate(assets, 1):
        conn.execute(
            "INSERT INTO assets (id, rightsholder_id, title, artist, isrc, iswc, spotify_id, label, kind, markets,"
            " ownership_pct, rights_type, release_date, revenue_cents, status, created_at)"
            " VALUES (?,1,?,?,?,?,?,?,?,?,?,?,?,?, 'active', ?)",
            (i, a[0], a[1], a[2], a[3], spotify_id(a[2]), a[4], a[5], a[6], a[7], a[8], d(a[9]), a[10],
             (now - timedelta(days=a[9])).isoformat()),
        )

    # (asset_id, upload, uploader, content_type, source, pct, kind, markets, streams, rev_cents, claim_type, reviewer, segment, status, hrs_ago)
    matches = [
        (1, "midnight (sped up)", "user_42aa", "Fan upload", "Spotify UGC", 97, "audio", 92, 412000, 184000, "Monetize", None, "0:44–1:38", "pending", 6),
        (4, "Static Bloom — full MV", "creator_lux", "User video", "Spotify Video", 71, "video", 8, 38000, 21000, "Review", None, "0:00–3:12", "pending", 14),
        (3, "Paper Planes live bootleg", "tapehead", "Fan upload", "Spotify UGC", 99, "audio", 184, 905000, 402000, "Monetize", "A. Okafor", "full", "cleared", 30),
        (4, "Static Bloom visualizer", "promo_de", "Canvas", "Spotify Canvas", 54, "video", 2, 12000, 6400, "Track", None, "loop", "disputed", 5),
        (5, "Lowlight 4-bar sample", "djsets", "DJ mix", "Spotify UGC", 68, "audio", 184, 221000, 98000, "Review", None, "1:02–1:09", "pending", 22),
        (6, "Cobalt — slowed + reverb", "moodloops", "Fan upload", "Spotify UGC", 88, "audio", 120, 168000, 120000, "Monetize", None, "full", "pending", 27),
        (2, "Golden Hour cover (inst.)", "studio_k", "Cover", "Spotify UGC", 43, "audio", 30, 9400, 3100, "Review", None, "full", "pending", 33),
        (7, "Northern Wires snippet", "shorts_bot", "Short", "Spotify Video", 61, "audio", 12, 4100, 1200, "Block", "A. Okafor", "0:20–0:35", "rejected", 40),
        (1, "midnight reprise — radio rip", "fm_caps", "Reupload", "Spotify UGC", 95, "audio", 150, 76000, 41000, "Monetize", None, "full", "pending", 48),
        (6, "cobalt edit pack", "edmpool", "Remix", "Spotify UGC", 82, "audio", 184, 134000, 96000, "Monetize", None, "0:30–2:10", "pending", 51),
        (8, "afterglow loop", "loopcat", "Canvas", "Spotify Canvas", 90, "video", 184, 58000, 28000, "Monetize", None, "loop", "cleared", 60),
        (3, "paper planes acoustic", "buskerz", "Cover", "Spotify UGC", 47, "audio", 90, 21000, 6900, "Review", None, "full", "pending", 70),
        (5, "lowlight full master leak", "leakwatch", "Reupload", "Spotify UGC", 99, "audio", 184, 33000, 188000, "Block", "A. Okafor", "full", "disputed", 8),
        (2, "golden hour nightcore", "speedcore", "Remix", "Spotify UGC", 76, "audio", 60, 44000, 19000, "Monetize", None, "full", "pending", 90),
    ]
    for i, m in enumerate(matches, 1):
        conn.execute(
            "INSERT INTO matches (id, asset_id, upload_title, uploader, content_type, source, match_pct,"
            " kind, markets, monthly_streams, revenue_cents, claim_type, reviewer, segment, status, detected_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11], m[12], m[13],
             (now - timedelta(hours=m[14])).isoformat()),
        )

    disputes = [
        ("SRC-2026-0041", 4, "Meridian Music Group", "promo_de", "Uploader submitted a sync license for DACH territories", "High", "open", "A. Okafor", 5, 3),
        ("SRC-2026-0039", 13, "Meridian Music Group", "leakwatch", "Full-master reupload; uploader claims fair use", "Critical", "open", "R. Nakamura", 8, 1),
    ]
    for i, dz in enumerate(disputes, 1):
        conn.execute(
            "INSERT INTO disputes (id, case_ref, match_id, claimant, respondent, reason, priority, status,"
            " assigned_to, opened_at, sla_deadline) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (i, dz[0], dz[1], dz[2], dz[3], dz[4], dz[5], dz[6], dz[7],
             (now - timedelta(hours=dz[8])).isoformat(), (now + timedelta(days=dz[9])).date().isoformat()),
        )

    # (label, descr, scope, action, territories, priority, enabled, threshold)
    policies = [
        ("Auto-claim high-confidence audio", "Audio matches at or above the threshold are claimed automatically", "Audio", "Monetize", "Worldwide", 1, 1, 95),
        ("Monetize user video", "Apply revenue claims to user video rather than takedown", "Video", "Monetize", "Worldwide", 2, 1, None),
        ("Honor territory restrictions", "Respect per-region licensing on every claim", "All", "Track", "Per-asset", 3, 1, None),
        ("Manual review band", "Route matches below the threshold to the review queue", "All", "Review", "Worldwide", 4, 1, 70),
        ("Block confirmed master leaks", "Take down full-master reuploads pending dispute", "Audio", "Block", "Worldwide", 5, 0, 98),
    ]
    for i, p in enumerate(policies, 1):
        conn.execute(
            "INSERT INTO policies (id, rightsholder_id, label, descr, scope, action, territories, priority, enabled, threshold)"
            " VALUES (?,1,?,?,?,?,?,?,?,?)",
            (i, p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]),
        )

    # Weekly inflow (newly detected matches) vs outflow (matches resolved).
    # Resolution outpaces detection every week, so the backlog (see
    # WEEKLY_BACKLOG_START) burns down 60 -> 13 and levels off near steady state.
    detected = [14, 16, 12, 15, 11, 14, 10, 13, 9, 12, 10, 12]
    resolved = [20, 21, 18, 20, 16, 18, 14, 16, 12, 15, 12, 13]
    for i in range(12):
        conn.execute("INSERT INTO weekly_stats (week, detected, resolved) VALUES (?,?,?)",
                     (f"W{i+1}", detected[i], resolved[i]))

    log(conn, "system", "seed", "Seeded fictional Meridian Music Group catalog")
    conn.commit()


# --- Reads ----------------------------------------------------------------

def rightsholder(conn: sqlite3.Connection) -> dict:
    return _row(conn.execute("SELECT * FROM rightsholders WHERE id=1").fetchone())


RESPONSE_WINDOW_DAYS = 7  # how long a flagged upload has to respond before it is overdue


def kpis(conn: sqlite3.Connection) -> dict:
    """Operational health, framed around the real goal: no infringing upload left
    unresolved. Open backlog is the number to drive to zero; pastWindow and
    oldestPendingDays surface infringement that has sat unaddressed too long."""
    g = lambda sql, *p: conn.execute(sql, p).fetchone()["n"]
    total = g("SELECT COUNT(*) AS n FROM matches")
    cleared = g("SELECT COUNT(*) AS n FROM matches WHERE status='cleared'")
    rejected = g("SELECT COUNT(*) AS n FROM matches WHERE status='rejected'")
    pending = g("SELECT COUNT(*) AS n FROM matches WHERE status='pending'")
    disputed = g("SELECT COUNT(*) AS n FROM matches WHERE status='disputed'")

    # Aging of still-open matches against the response window.
    now = datetime.now(timezone.utc)
    ages = []
    for r in conn.execute("SELECT detected_at FROM matches WHERE status IN ('pending','disputed')"):
        try:
            ages.append((now - datetime.fromisoformat(r["detected_at"])).total_seconds() / 86400)
        except (ValueError, TypeError):
            pass

    return {
        "pendingMatches": pending,
        "openDisputes": g("SELECT COUNT(*) AS n FROM disputes WHERE status='open'"),
        "openBacklog": pending + disputed,
        "pastWindow": sum(1 for a in ages if a > RESPONSE_WINDOW_DAYS),
        "oldestPendingDays": round(max(ages)) if ages else 0,
        "resolutionRate": round((cleared + rejected) / total * 100) if total else 0,
        "matchRate": round(cleared / total * 100) if total else 0,
        "assetsManaged": g("SELECT COUNT(*) AS n FROM assets"),
        "catalogRevenue": g("SELECT COALESCE(SUM(revenue_cents),0) AS n FROM assets"),
        "revenueAtRisk": g("SELECT COALESCE(SUM(revenue_cents),0) AS n FROM matches WHERE status='pending'"),
    }


def match_counts(conn: sqlite3.Connection) -> dict:
    counts = {s: 0 for s in MATCH_STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM matches GROUP BY status"):
        counts[r["status"]] = r["n"]
    counts["all"] = sum(counts[s] for s in MATCH_STATUSES)
    return counts


_MATCH_SELECT = (
    "SELECT m.*, a.title AS asset_title, a.artist AS asset_artist, a.isrc AS asset_isrc, "
    "a.iswc AS asset_iswc, a.spotify_id AS asset_spotify_id, "
    "a.ownership_pct AS asset_ownership, a.rights_type AS asset_rights "
    "FROM matches m JOIN assets a ON a.id = m.asset_id "
)


def list_matches(conn, status=None, q=None, sort="detected", direction="desc",
                 page=1, page_size=10) -> tuple[list[dict], int]:
    where, params = [], []
    if status and status in MATCH_STATUSES:
        where.append("m.status = ?"); params.append(status)
    if q:
        where.append("(m.upload_title LIKE ? OR m.uploader LIKE ? OR a.title LIKE ? OR a.isrc LIKE ?)")
        params += [f"%{q}%"] * 4
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS n FROM matches m JOIN assets a ON a.id=m.asset_id{clause}",
                         params).fetchone()["n"]
    col = MATCH_SORTS.get(sort, "m.detected_at")
    dir_sql = "ASC" if direction == "asc" else "DESC"
    page = max(1, page)
    rows = conn.execute(
        f"{_MATCH_SELECT}{clause} ORDER BY {col} {dir_sql} LIMIT ? OFFSET ?",
        (*params, page_size, (page - 1) * page_size),
    ).fetchall()
    return [_row(r) for r in rows], total


def get_match(conn, match_id) -> dict | None:
    r = conn.execute(_MATCH_SELECT + " WHERE m.id = ?", (match_id,)).fetchone()
    return _row(r) if r else None


def list_disputes(conn, status=None) -> list[dict]:
    sql = (
        "SELECT d.*, m.upload_title, m.uploader, m.revenue_cents, a.title AS asset_title "
        "FROM disputes d JOIN matches m ON m.id=d.match_id JOIN assets a ON a.id=m.asset_id "
    )
    params = ()
    if status:
        sql += "WHERE d.status = ? "; params = (status,)
    sql += "ORDER BY (d.status='open') DESC, d.opened_at DESC"
    return [_row(r) for r in conn.execute(sql, params).fetchall()]


def get_dispute(conn, dispute_id) -> dict | None:
    r = conn.execute(
        "SELECT d.*, m.upload_title, m.uploader, m.match_pct, m.content_type, m.revenue_cents, "
        "a.title AS asset_title, a.artist AS asset_artist, a.isrc AS asset_isrc "
        "FROM disputes d JOIN matches m ON m.id=d.match_id JOIN assets a ON a.id=m.asset_id WHERE d.id=?",
        (dispute_id,),
    ).fetchone()
    return _row(r) if r else None


def list_policies(conn) -> list[dict]:
    return [_row(r) for r in conn.execute("SELECT * FROM policies ORDER BY priority").fetchall()]


def list_activity(conn, limit=10) -> list[dict]:
    return [_row(r) for r in conn.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def weekly(conn) -> list[dict]:
    """Weekly inflow (detected) vs outflow (resolved) with the running open
    backlog derived from the seeded starting level. Backlog is the stock the
    operation burns down; detected/resolved are the flows that move it."""
    rows = conn.execute("SELECT week, detected, resolved FROM weekly_stats ORDER BY id").fetchall()
    out, backlog = [], WEEKLY_BACKLOG_START
    for r in rows:
        backlog = max(0, backlog + r["detected"] - r["resolved"])
        out.append({"week": r["week"], "detected": r["detected"],
                    "resolved": r["resolved"], "backlog": backlog})
    return out


def list_assets(conn, q=None, sort="released", direction="desc", page=1, page_size=12) -> tuple[list[dict], int]:
    base = "FROM assets a"
    where, params = [], []
    if q:
        where.append("(a.title LIKE ? OR a.artist LIKE ? OR a.isrc LIKE ?)")
        params += [f"%{q}%"] * 3
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS n {base}{clause}", params).fetchone()["n"]
    col = ASSET_SORTS.get(sort, "a.release_date")
    dir_sql = "ASC" if direction == "asc" else "DESC"
    rows = conn.execute(
        "SELECT a.*, (SELECT COUNT(*) FROM matches m WHERE m.asset_id=a.id) AS claims "
        f"{base}{clause} ORDER BY {col} {dir_sql} LIMIT ? OFFSET ?",
        (*params, page_size, (max(1, page) - 1) * page_size),
    ).fetchall()
    return [_row(r) for r in rows], total


def content_type_breakdown(conn) -> list[dict]:
    return [_row(r) for r in conn.execute(
        "SELECT content_type AS label, COUNT(*) AS n, COALESCE(SUM(revenue_cents),0) AS revenue "
        "FROM matches GROUP BY content_type ORDER BY n DESC").fetchall()]


def top_works(conn, limit=6) -> list[dict]:
    return [_row(r) for r in conn.execute(
        "SELECT a.title, a.artist, a.revenue_cents, "
        "(SELECT COUNT(*) FROM matches m WHERE m.asset_id=a.id) AS claims "
        "FROM assets a ORDER BY claims DESC, a.revenue_cents DESC LIMIT ?", (limit,)).fetchall()]


# --- Mutations ------------------------------------------------------------

def apply_match_action(conn, match_id, action, actor="you") -> dict:
    if action not in ACTION_TO_STATUS:
        raise ValueError(f"Unknown action: {action!r}")
    match = get_match(conn, match_id)
    if not match:
        raise ValueError(f"No match with id {match_id}")
    conn.execute("UPDATE matches SET status=? WHERE id=?", (ACTION_TO_STATUS[action], match_id))
    if action == "dispute" and not conn.execute(
            "SELECT id FROM disputes WHERE match_id=? AND status='open'", (match_id,)).fetchone():
        ref = f"SRC-2026-{1000 + match_id:04d}"
        conn.execute(
            "INSERT INTO disputes (case_ref, match_id, claimant, respondent, reason, priority, status, opened_at, sla_deadline)"
            " VALUES (?,?,?,?,?,?, 'open', ?, ?)",
            (ref, match_id, "Meridian Music Group", match["uploader"],
             "Flagged for manual dispute review", "Medium", _now(),
             (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()),
        )
    log(conn, actor, action, f"{action} match #{match_id} ({match['asset_title']})")
    conn.commit()
    return get_match(conn, match_id)


RESPONSE_CHOICES = {
    "license":   ("Respondent asserts a direct license with the copyright owner", "disputed", "High"),
    "exception": ("Respondent claims a copyright exception (quotation, criticism, review, parody)", "disputed", "Medium"),
    "never":     ("Respondent states the content was never used; re-scan requested", "disputed", "Low"),
    "unpublish": ("Respondent unpublished the upload to remove the content", "cleared", None),
}


def respondent_submit(conn, match_id, choice, actor="respondent") -> dict:
    """Handle the flagged respondent's review-form choice. Contesting choices
    open a dispute and mark the match disputed; unpublishing clears it."""
    if choice not in RESPONSE_CHOICES:
        raise ValueError("Please choose one option before submitting")
    m = get_match(conn, match_id)
    if not m:
        raise ValueError(f"No match with id {match_id}")
    reason, new_status, priority = RESPONSE_CHOICES[choice]
    conn.execute("UPDATE matches SET status=? WHERE id=?", (new_status, match_id))
    if new_status == "disputed" and not conn.execute(
            "SELECT id FROM disputes WHERE match_id=? AND status='open'", (match_id,)).fetchone():
        ref = f"SRC-2026-{2000 + match_id:04d}"
        conn.execute(
            "INSERT INTO disputes (case_ref, match_id, claimant, respondent, reason, priority, status, opened_at, sla_deadline)"
            " VALUES (?,?,?,?,?,?, 'open', ?, ?)",
            (ref, match_id, "Meridian Music Group", m["uploader"], reason, priority, _now(),
             (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()),
        )
    log(conn, actor, "respond", f"Respondent on match #{match_id}: {choice}")
    conn.commit()
    return {"choice": choice, "reason": reason, "status": new_status}


def bulk_match_action(conn, ids, action, actor="you") -> list[int]:
    if action not in ("approve", "reject"):
        raise ValueError("Bulk action must be 'approve' or 'reject'")
    changed = []
    for mid in ids:
        m = get_match(conn, mid)
        if m and m["status"] == "pending":
            conn.execute("UPDATE matches SET status=? WHERE id=?", (ACTION_TO_STATUS[action], mid))
            changed.append(mid)
    log(conn, actor, action, f"Bulk {action} on {len(changed)} match(es)")
    conn.commit()
    return changed


def resolve_dispute(conn, dispute_id, resolution, actor="you") -> dict:
    if resolution not in DISPUTE_RESOLUTIONS:
        raise ValueError(f"Unknown resolution: {resolution!r}")
    d = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    if not d:
        raise ValueError(f"No dispute with id {dispute_id}")
    conn.execute("UPDATE disputes SET status='resolved', resolution=?, resolved_at=? WHERE id=?",
                 (resolution, _now(), dispute_id))
    conn.execute("UPDATE matches SET status=? WHERE id=?", (DISPUTE_RESOLUTIONS[resolution], d["match_id"]))
    log(conn, actor, "resolve", f"Dispute {d['case_ref']} resolved: {resolution}")
    conn.commit()
    return _row(conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone())


def set_policy(conn, policy_id, enabled=None, threshold=None, actor="you") -> dict:
    p = conn.execute("SELECT * FROM policies WHERE id=?", (policy_id,)).fetchone()
    if not p:
        raise ValueError(f"No policy with id {policy_id}")
    if enabled is not None:
        conn.execute("UPDATE policies SET enabled=? WHERE id=?", (1 if enabled else 0, policy_id))
    if threshold is not None:
        conn.execute("UPDATE policies SET threshold=? WHERE id=?", (int(threshold), policy_id))
    log(conn, actor, "policy", f"Updated policy #{policy_id} ({p['label']})")
    conn.commit()
    return _row(conn.execute("SELECT * FROM policies WHERE id=?", (policy_id,)).fetchone())


def create_asset(conn, title, artist, kind, markets, rights_type="Master", actor="you") -> dict:
    title, artist = (title or "").strip(), (artist or "").strip()
    if not title or not artist:
        raise ValueError("Title and artist are required")
    if kind not in ("audio", "video"):
        raise ValueError("Type must be 'audio' or 'video'")
    try:
        markets = int(markets)
    except (TypeError, ValueError):
        raise ValueError("Markets must be a number")
    if not 0 <= markets <= 200:
        raise ValueError("Markets must be between 0 and 200")
    seq = conn.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"] + 1
    isrc = f"ZZMMG26{seq:05d}"
    cur = conn.execute(
        "INSERT INTO assets (rightsholder_id, title, artist, isrc, iswc, spotify_id, label, kind, markets,"
        " ownership_pct, rights_type, release_date, revenue_cents, status, created_at)"
        " VALUES (1,?,?,?,NULL,?,'Meridian',?,?,100,?,?,0,'active',?)",
        (title, artist, isrc, spotify_id(isrc), kind, markets, rights_type,
         datetime.now(timezone.utc).date().isoformat(), _now()),
    )
    log(conn, actor, "asset", f"Registered asset “{title}” ({isrc})")
    conn.commit()
    return _row(conn.execute("SELECT * FROM assets WHERE id=?", (cur.lastrowid,)).fetchone())


def bootstrap(path: str | None = None) -> None:
    conn = connect(path)
    try:
        init_db(conn)
        seed(conn)
    finally:
        conn.close()
