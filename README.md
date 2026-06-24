# Spotify Rights Center (SRC) — simulated rights platform


## What actually works

A genuine **multi-page** app — each nav item is a URL with a
server-rendered page. Filtering, sorting, and pagination are URL params;
actions are HTML form posts that mutate SQLite and redirect back.

- **Overview** (`/`) — executive KPIs (revenue at risk / recovered, clear rate),
  highest-value matches, disputes near SLA, activity feed, 12-week chart.
- **Match queue** (`/matches`) — status tabs with counts, search, **sortable**
  columns (confidence, revenue), per-row approve/reject/dispute, **bulk select +
  bulk actions with a confirm step on reject**, pagination, and a **detail page**
  per match (`/matches/<id>`) with full metadata + matched-reference info.
- **Disputes** (`/disputes`) — case list (priority, SLA countdown, revenue at
  stake) and a **case page** (`/disputes/<id>`) with parties, reason, and
  uphold/withdraw that propagates to the match.
- **Reference catalog** (`/catalog`) — sortable table (ISRC/ISWC, rights split,
  ownership, territory, claims, revenue) + **Register asset** modal.
- **Policies** (`/policies`) — enforcement rules with scope/action/territory,
  priority order, enable toggles, and editable thresholds.
- **Analytics** (`/analytics`) — scanned/actioned chart, match-outcome
  breakdown, by-content-type table, top claimed works.

### Respondent flow (the uploader's side)

The flagged uploader's experience, modelled on Spotify's "third-party content"
review: a notice page (`/respond/<match_id>`) with a countdown, and a review
form (`/respond/<match_id>/review`) where they assert a license, claim a
copyright exception, request a re-scan, or unpublish. Contesting choices **open
a dispute** the rights admin then sees; unpublishing clears the match. Admin
match/dispute pages link to a live preview of this notice.

**Palette:** Spotify green `#1ED760` (primary action, black text on it), white
`#FFFFFF`, near-black `#121212`, and the neutral gray ramp — no other hues.

No login, no OAuth, no external services — just run it.

## Stack

- **Backend:** Flask + Jinja templates (`app.py`, `templates/`) on a SQLite data
  layer (`db.py`). Server-rendered pages; form-post actions; flash messages.
- **Frontend:** Hallmark design system (`tokens.css` + `styles.css`) with a tiny
  `app.js` for the register-asset modal, bulk-select, and confirm dialogs.
- **DB:** `src.db`, created and seeded automatically on first run (gitignored).

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:3000>. To reset to a clean seed, delete `src.db` and
restart.

## Data model (`db.py`)

| Table | Purpose |
|---|---|
| `rightsholders` | the org operating the catalog |
| `assets` | reference works (title, artist, **ISRC**, audio/video, market count) |
| `matches` | detected uses, with `match_pct`, territories, and a status |
| `disputes` | open/resolved disputes linked to a match |
| `policies` | enforcement rules (enabled + threshold) |
| `activity` | append-only audit log of every action |
| `weekly_stats` | 12-week scanned/actioned series for analytics |

Match status flow: `pending → cleared | rejected | disputed`; resolving a
dispute moves the match to `cleared` (upheld) or `rejected` (withdrawn).

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/` `/matches` `/disputes` `/catalog` `/policies` `/analytics` | pages |
| GET | `/matches/<id>` · `/disputes/<id>` | detail pages |
| GET | `/matches?status=&q=&sort=&dir=&page=` | filtered/sorted/paged queue |
| GET | `/catalog?q=&sort=&dir=&page=` | filtered/sorted/paged catalog |
| POST | `/matches/<id>/action` (`action`) | approve / reject / dispute |
| POST | `/matches/bulk` (`ids[]`, `action`) | bulk approve / reject |
| POST | `/disputes/<id>/resolve` (`resolution`) | upheld / withdrawn |
| POST | `/policies/<id>` (`enabled`, `threshold`) | update policy |
| POST | `/catalog` (`title`, `artist`, `kind`, `markets`) | register asset |

Inputs are validated and parameterized; bad input flashes an error and
redirects back.

## Tests

```bash
pytest -q     # 23 tests: seed, KPIs, counts, list/filter/paginate,
              # match actions, bulk, disputes, policies, catalog, analytics
```

Each test runs against a fresh in-memory database.

## Notes

- This project is not affiliated with or endorsed by Spotify.
