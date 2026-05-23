# FareRadar — Session Handoff

## Project Overview

**FareRadar** is a Vienna public transit fare inspection tracker.

- **`main-azure.py`** — Telegram listener that picks up messages from a target group, runs them through Azure OpenAI (GPT), and writes structured events to Azure Table Storage.
- **`app.py`** — Streamlit dashboard that reads from Azure Table Storage and displays active/closed inspection events on a map and in tables.
- **`wienerlinien-ogd-haltestellen.csv`** — Local CSV of all Wiener Linien stops with coordinates (used for fuzzy station-to-coordinate lookup on the map).

### Azure Table Storage schema (`kontrollen` table)

| Field | Type | Notes |
|---|---|---|
| `PartitionKey` | string | Always `"Kontrolle"` (hardcoded) |
| `RowKey` | string | Auto-generated from message timestamp |
| `ereignis_typ` | string | `"Beginn"` or `"Ende"` |
| `linie` | string | e.g. `"U1"`, `"13A"` — or empty |
| `ort` | string | Station name — or empty |
| `zusammenfassung` | string | One-sentence AI summary |
| `konfidenz` | float | `0.0` – `1.0` |
| `gestartet_am` | string | ISO timestamp from Telegram message |
| `beendet_am` | string | `""` = active, ISO timestamp = closed |

**Active events**: `beendet_am == ""`
**Closed events**: `beendet_am != ""`

---

## Changes Made This Session

### `main-azure.py`

#### 1. Simplified AI prompt
- Removed `kategorie` field (always `"Kontrolle"`, hardcoded in storage)
- Removed `wichtig` field (unused, dropped entirely)
- `ereignis_typ` now only `Beginn` / `Ende` (removed `Einzelmeldung`)

#### 2. Confidence gate (< 0.2 → dropped)
```python
if konfidenz < 0.2:
    print(f"  → Zu niedrige Konfidenz ({konfidenz:.2f}), Ereignis wird nicht gespeichert.")
    return
```

#### 3. Deduplication on Beginn
Before creating a new "Beginn" event, checks Azure for an already-open event at the same line + station. Two-pass: exact (line + station) → station only. Silently drops if duplicate found.

#### 4. Ende matching — two-pass with fuzzy fallback
- **Pass 1**: Exact match on `linie` + `ort`
- **Pass 2**: Fetches all open events, runs `rapidfuzz` `fuzz.WRatio` against their `ort` values (threshold ≥ 70). Handles typos like "Erdbergg" → "Erdberg".

#### 5. Unmatched "Ende" goes straight to closed
If an "Ende" message can't find any open event to close, it's stored with `beendet_am = its own timestamp` so it lands in the closed table — not the active one.

#### 6. AUTO_CLOSE_MINUTES → env var, default 60
```python
AUTO_CLOSE_MINUTES = int(os.getenv("AUTO_CLOSE_MINUTES", 60))
```
Set `AUTO_CLOSE_MINUTES=90` (or any value) in `.env` to override.

---

### `app.py`

#### 7. Auto-refresh → streamlit-autorefresh
Replaced broken JS `window.parent.location.reload()` with:
```python
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=30_000, key="autorefresh")
```
Sidebar filter state is now preserved across refreshes (no page flash).

#### 8. `ereignis_typ` column added to both tables
Active and closed event tables now show `"Ereignistyp"` (Beginn/Ende) as the first column.

#### 9. U-Bahn line drawing on map
Draws the actual route of any U-Bahn line that has an active event, using the official Wien WFS GeoJSON:

```
https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature
  &version=1.1.0&typeName=ogdwien:UBAHNOGD&srsName=EPSG:4326&outputFormat=json
```

- Fully isolated: `load_ubahn_geojson()` returns `None` on any network error — map renders normally without it.
- Cached 1 hour (`ttl=3600`).
- Only draws lines that have active events (map stays clean).
- LINFO → line name mapping (internal WFS property):

```python
LINFO_TO_LINE = {1: "U1", 2: "U2", 3: "U3", 4: "U4", 6: "U6"}
```

Official Wien U-Bahn colors used for polylines.

---

## Remaining Recommendations (not implemented)

| # | What | Effort |
|---|---|---|
| 6 | Store `sender_name` from Telegram in Azure | Low |
| 7 | Show computed duration on closed events table | Low |
| 8 | Replace useless `Kategorie` sidebar filter with `Ereignistyp` filter | Low |
| 9 | Remove dead markdown-stripping code in `analyse_mit_ki` (lines 66–70) | Trivial |
| 10 | Remove dead `KATEGORIE_COLOR` entries (Unfall/Stau/Sonstiges) | Trivial |
| 11 | Fix deprecated `asyncio.get_event_loop().create_task()` → `asyncio.create_task()` | Trivial |
| 12 | Add date-range filter to `load_events()` to cap Azure costs as table grows | Medium |

---

## Environment Variables (`.env`)

```
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TARGET_GROUP=
AZURE_AI_FOUNDRY_KEY=
AZURE_AI_FOUNDRY_ENDPOINT=
AZURE_AI_FOUNDRY_DEPLOYMENT=
AZURE_STORAGE_CONNECTION_STRING=
AUTO_CLOSE_MINUTES=60   # optional, default is 60
```
