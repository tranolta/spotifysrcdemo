"""Spotify Rights Center (SRC) — multi-page rights-management platform.

A self-contained, FUNCTIONAL tool: separate server-rendered pages for the
overview, match queue (with detail pages), disputes (with case pages), reference
catalog, enforcement policies, and analytics. Filtering, sorting, and pagination
are driven by URL query params; actions are HTML form posts that mutate the
SQLite database and redirect back. No JavaScript framework, no OAuth.

This is a SIMULATION with seeded fictional data — the public Spotify Web API has
no rights/Content-ID endpoints. It is badged as a demo in the UI.

Run:  python app.py   ->   http://127.0.0.1:3000
"""

from __future__ import annotations

import math
import os
import secrets
from datetime import date, datetime, timedelta

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, send_from_directory, url_for)

import db

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = {"app.js", "styles.css", "tokens.css",
          "spotify-logo-white.svg", "spotify-logo-black.svg", "spotify-logo-green.svg"}
MATCH_PAGE = 10
ASSET_PAGE = 12

app = Flask(__name__, template_folder="templates", static_folder=None)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(16)


# --- DB lifecycle ---------------------------------------------------------

def conn():
    if "conn" not in g:
        g.conn = db.connect()
    return g.conn


@app.teardown_appcontext
def _close(_exc):
    c = g.pop("conn", None)
    if c is not None:
        c.close()


@app.context_processor
def _inject_nav():
    k = db.kpis(conn())

    def urlmod(**kw):
        args = {**request.args.to_dict(), **kw}
        args = {k2: v for k2, v in args.items() if v not in (None, "")}
        return url_for(request.endpoint, **args)

    return {"nav": {"pending": k["pendingMatches"], "disputes": k["openDisputes"]},
            "rh": db.rightsholder(conn())["name"], "urlmod": urlmod}


# --- Template filters -----------------------------------------------------

@app.template_filter("money")
def money(cents):
    return f"${(cents or 0) / 100:,.0f}"


@app.template_filter("moneyk")
def moneyk(cents):
    d = (cents or 0) / 100
    if d >= 1_000_000:
        return f"${d / 1_000_000:.1f}M"
    if d >= 1_000:
        return f"${d / 1_000:.1f}k"
    return f"${d:.0f}"


@app.template_filter("compact")
def compact(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


@app.template_filter("reltime")
def reltime(iso):
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    secs = max(0, (datetime.now(then.tzinfo) - then).total_seconds())
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


@app.template_filter("daysleft")
def daysleft(iso_date):
    if not iso_date:
        return None
    try:
        return (date.fromisoformat(iso_date) - date.today()).days
    except ValueError:
        return None


@app.template_filter("territory")
def territory(markets):
    if markets >= 180:
        return "Worldwide"
    return f"{markets} markets"


@app.template_filter("hue")
def hue(text):
    """Deterministic 0–359 hue from a string, for the monogram art tiles that
    stand in for missing cover art (this is a simulation with no artwork URLs)."""
    h = 0
    for ch in (text or "?"):
        h = (h * 31 + ord(ch)) % 360
    return h


# --- helpers --------------------------------------------------------------

def _pageinfo(total, page, size):
    pages = max(1, math.ceil(total / size))
    page = min(max(1, page), pages)
    start = (page - 1) * size
    return {"page": page, "pages": pages, "total": total,
            "from": start + 1 if total else 0, "to": min(start + size, total),
            "has_prev": page > 1, "has_next": page < pages}


def _int(name, default):
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def _back(default):
    return redirect(request.form.get("next") or request.referrer or default)


# --- Chart geometry -------------------------------------------------------

CHART_VB_W, CHART_VB_H = 720, 200
_CH_PAD = {"l": 6, "r": 6, "t": 16, "b": 26}


def _burndown(weekly):
    """Build SVG geometry for the backlog burndown. Backlog (a stock) and the
    detected/resolved flows are scaled on independent vertical axes so all three
    read clearly; tooltips carry the real integers. Pure presentation math, kept
    out of the data layer and the template."""
    if not weekly:
        return None
    n = len(weekly)
    iw = CHART_VB_W - _CH_PAD["l"] - _CH_PAD["r"]
    ih = CHART_VB_H - _CH_PAD["t"] - _CH_PAD["b"]
    bmax = max(w["backlog"] for w in weekly) or 1
    fmax = max(max(w["detected"], w["resolved"]) for w in weekly) or 1
    span = (n - 1) or 1
    x = lambda i: round(_CH_PAD["l"] + iw * i / span, 1)
    yb = lambda v: round(_CH_PAD["t"] + ih * (1 - v / bmax), 1)
    yf = lambda v: round(_CH_PAD["t"] + ih * (1 - v / fmax), 1)
    base = round(_CH_PAD["t"] + ih, 1)
    pts = [{
        "week": w["week"], "x": x(i),
        "detected": w["detected"], "resolved": w["resolved"], "backlog": w["backlog"],
        "yd": yf(w["detected"]), "yr": yf(w["resolved"]), "yb": yb(w["backlog"]),
        "hx": round(x(i) - iw / span / 2, 1),
    } for i, w in enumerate(weekly)]
    poly = lambda key: " ".join(f"{p['x']},{p[key]}" for p in pts)
    return {
        "w": CHART_VB_W, "h": CHART_VB_H, "base": base, "colw": round(iw / span, 1),
        "pts": pts, "last": pts[-1], "first": pts[0],
        "backlog": poly("yb"), "detected": poly("yd"), "resolved": poly("yr"),
        "area": f"{pts[0]['x']},{base} {poly('yb')} {pts[-1]['x']},{base}",
    }


# --- Static ---------------------------------------------------------------

@app.get("/assets/<path:filename>")
def static_files(filename):
    if filename not in ASSETS:
        abort(404)
    return send_from_directory(HERE, filename)


# --- Pages ----------------------------------------------------------------

@app.get("/")
def overview():
    c = conn()
    matches, _ = db.list_matches(c, sort="revenue", direction="desc", page=1, page_size=6)
    return render_template(
        "overview.html", active="overview", kpis=db.kpis(c), counts=db.match_counts(c),
        chart=_burndown(db.weekly(c)), top_matches=matches,
        disputes=db.list_disputes(c, status="open"), activity=db.list_activity(c, 8))


@app.get("/matches")
def matches():
    c = conn()
    status = request.args.get("status") or None
    q = request.args.get("q") or None
    sort = request.args.get("sort", "detected")
    direction = request.args.get("dir", "desc")
    page = _int("page", 1)
    rows, total = db.list_matches(c, status, q, sort, direction, page, MATCH_PAGE)
    return render_template(
        "matches.html", active="matches", matches=rows, counts=db.match_counts(c),
        status=status, q=q or "", sort=sort, dir=direction,
        page=_pageinfo(total, page, MATCH_PAGE))


@app.get("/matches/<int:match_id>")
def match_detail(match_id):
    m = db.get_match(conn(), match_id)
    if not m:
        abort(404)
    return render_template("match_detail.html", active="matches", m=m)


@app.post("/matches/<int:match_id>/action")
def match_action(match_id):
    try:
        db.apply_match_action(conn(), match_id, request.form.get("action", ""))
        flash(f"Match #{match_id} updated.", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return _back(url_for("matches"))


@app.post("/matches/bulk")
def matches_bulk():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    try:
        changed = db.bulk_match_action(conn(), ids, request.form.get("action", ""))
        flash(f"{len(changed)} match(es) updated.", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return _back(url_for("matches"))


@app.get("/disputes")
def disputes():
    c = conn()
    status = request.args.get("status") or None
    return render_template("disputes.html", active="disputes",
                           disputes=db.list_disputes(c, status), status=status)


@app.get("/disputes/<int:dispute_id>")
def dispute_detail(dispute_id):
    d = db.get_dispute(conn(), dispute_id)
    if not d:
        abort(404)
    return render_template("dispute_detail.html", active="disputes", d=d)


@app.post("/disputes/<int:dispute_id>/resolve")
def dispute_resolve(dispute_id):
    try:
        db.resolve_dispute(conn(), dispute_id, request.form.get("resolution", ""))
        flash("Dispute resolved.", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return _back(url_for("disputes"))


@app.get("/catalog")
def catalog():
    c = conn()
    q = request.args.get("q") or None
    sort = request.args.get("sort", "released")
    direction = request.args.get("dir", "desc")
    page = _int("page", 1)
    rows, total = db.list_assets(c, q, sort, direction, page, ASSET_PAGE)
    return render_template("catalog.html", active="catalog", assets=rows,
                           q=q or "", sort=sort, dir=direction,
                           page=_pageinfo(total, page, ASSET_PAGE))


@app.post("/catalog")
def catalog_create():
    try:
        db.create_asset(conn(), request.form.get("title", ""), request.form.get("artist", ""),
                        request.form.get("kind", ""), request.form.get("markets", 0),
                        request.form.get("rights_type", "Master"))
        flash("Asset registered.", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("catalog"))


@app.get("/policies")
def policies():
    return render_template("policies.html", active="policies", policies=db.list_policies(conn()))


@app.post("/policies/<int:policy_id>")
def policy_update(policy_id):
    enabled = request.form.get("enabled")
    threshold = request.form.get("threshold")
    try:
        db.set_policy(conn(), policy_id,
                      enabled=(enabled == "on") if enabled is not None or "toggle" in request.form else None,
                      threshold=int(threshold) if threshold else None)
        flash("Policy updated.", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return _back(url_for("policies"))


def _hours_left(m):
    try:
        detected = datetime.fromisoformat(m["detected_at"])
    except (ValueError, KeyError):
        return None
    window = detected + timedelta(days=7)
    left = (window - datetime.now(detected.tzinfo)).total_seconds() / 3600
    return max(0, round(left))


@app.get("/respond/<int:match_id>")
def respond_notice(match_id):
    m = db.get_match(conn(), match_id)
    if not m:
        abort(404)
    return render_template("respond_notice.html", m=m, hours=_hours_left(m))


@app.get("/respond/<int:match_id>/review")
def respond_review(match_id):
    m = db.get_match(conn(), match_id)
    if not m:
        abort(404)
    return render_template("respond_review.html", m=m)


@app.post("/respond/<int:match_id>")
def respond_submit(match_id):
    try:
        outcome = db.respondent_submit(conn(), match_id, request.form.get("choice", ""))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("respond_review", match_id=match_id))
    return render_template("respond_done.html", m=db.get_match(conn(), match_id), outcome=outcome)


@app.get("/analytics")
def analytics():
    c = conn()
    return render_template("analytics.html", active="analytics", kpis=db.kpis(c),
                           counts=db.match_counts(c), chart=_burndown(db.weekly(c)),
                           by_type=db.content_type_breakdown(c), top=db.top_works(c))


if __name__ == "__main__":
    db.bootstrap()
    app.run(host="127.0.0.1", port=3000, debug=True)
