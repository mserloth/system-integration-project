import os
import urllib.request
import pandas as pd
import folium
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium
from azure.data.tables import TableServiceClient
from dotenv import load_dotenv, find_dotenv
from rapidfuzz import process, fuzz

load_dotenv(find_dotenv())

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CSV_PATH = "wienerlinien-ogd-haltestellen.csv"

st.set_page_config(page_title="FareRadar", page_icon="🚍", layout="wide")

KATEGORIE_COLOR = {
    "Kontrolle": "red",
    "Unfall": "orange",
    "Stau": "blue",
    "Sonstiges": "gray",
}

# U-Bahn line drawing — LINFO is the internal line number in the Wien WFS
LINFO_TO_LINE = {1: "U1", 2: "U2", 3: "U3", 4: "U4", 6: "U6"}
UBAHN_LINE_COLOR = {
    "U1": "#E2001A",
    "U2": "#9B59B6",
    "U3": "#EF7C00",
    "U4": "#23A127",
    "U6": "#964B00",
}
_WFS_URL = (
    "https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature"
    "&version=1.1.0&typeName=ogdwien:UBAHNOGD&srsName=EPSG:4326&outputFormat=json"
)


@st.cache_data(ttl=3600)
def load_ubahn_geojson() -> dict | None:
    try:
        import json
        with urllib.request.urlopen(_WFS_URL, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def draw_ubahn_lines(m: folium.Map, active_lines: set, geojson: dict | None):
    if not geojson:
        return
    for feature in geojson.get("features", []):
        linfo = (feature.get("properties") or {}).get("LINFO")
        line_name = LINFO_TO_LINE.get(linfo)
        if line_name not in active_lines:
            continue
        coords = (feature.get("geometry") or {}).get("coordinates", [])
        if not coords:
            continue
        folium.PolyLine(
            locations=[[c[1], c[0]] for c in coords],
            color=UBAHN_LINE_COLOR.get(line_name, "#888888"),
            weight=5,
            opacity=0.7,
            tooltip=line_name,
        ).add_to(m)


@st.cache_data(ttl=30)
def load_stations() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, sep=";")
    return df[["PlatformText", "Longitude", "Latitude"]].drop_duplicates("PlatformText")


@st.cache_data(ttl=30)
def load_events() -> pd.DataFrame:
    svc = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    client = svc.get_table_client("kontrollen")
    rows = list(client.list_entities())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["beendet_am"] = df.get("beendet_am", "").fillna("")
    return df


def fuzzy_coords(ort: str, stations: pd.DataFrame):
    if not ort or stations.empty:
        return None, None
    result = process.extractOne(ort, stations["PlatformText"], scorer=fuzz.WRatio)
    if result is None or result[1] < 70:
        return None, None
    row = stations[stations["PlatformText"] == result[0]].iloc[0]
    return float(row["Latitude"]), float(row["Longitude"])


def build_map(active: pd.DataFrame, stations: pd.DataFrame, geojson: dict | None) -> folium.Map:
    m = folium.Map(location=[48.21, 16.37], zoom_start=12, tiles="CartoDB positron")
    active_lines = {str(row.get("linie") or "") for _, row in active.iterrows()}
    draw_ubahn_lines(m, active_lines, geojson)
    for _, row in active.iterrows():
        ort = str(row.get("ort") or "")
        lat, lon = fuzzy_coords(ort, stations)
        if lat is None:
            continue
        kategorie = str(row.get("PartitionKey") or "Sonstiges")
        color = KATEGORIE_COLOR.get(kategorie, "gray")
        linie = str(row.get("linie") or "—")
        zusammenfassung = str(row.get("zusammenfassung") or "")
        popup_html = f"<b>{ort}</b><br>Linie: {linie}<br>Typ: {kategorie}<br>{zusammenfassung}"
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"Linie {linie} – {ort}",
            icon=folium.Icon(color=color, icon="exclamation-sign", prefix="glyphicon"),
        ).add_to(m)
    return m


# ── Layout ──────────────────────────────────────────────────────────────────

st_autorefresh(interval=30_000, key="autorefresh")

st.title("FareRadar — Kontrollübersicht Wien")

stations = load_stations()
events = load_events()
ubahn_geojson = load_ubahn_geojson()

if events.empty:
    st.info("Noch keine Ereignisse in der Datenbank.")
    st.stop()

active = events[events["beendet_am"] == ""].copy()
closed = events[events["beendet_am"] != ""].copy()

# ── Sidebar filters ──────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Filter")
    all_lines = sorted(events["linie"].dropna().unique().tolist())
    selected_lines = st.multiselect("Linie", all_lines, default=all_lines)
    all_cats = sorted(events["PartitionKey"].dropna().unique().tolist())
    selected_cats = st.multiselect("Kategorie", all_cats, default=all_cats)
    st.divider()
    if st.button("Jetzt aktualisieren"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Daten werden alle 30 Sekunden automatisch aktualisiert.")

if selected_lines:
    active = active[active["linie"].isin(selected_lines)]
if selected_cats:
    active = active[active["PartitionKey"].isin(selected_cats)]

# ── Metrics ──────────────────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)
col1.metric("Aktive Ereignisse", len(active))
col2.metric("Abgeschlossen", len(closed))
col3.metric("Gesamt", len(events))

st.divider()

# ── Map ───────────────────────────────────────────────────────────────────────

st.subheader(f"Karte — Aktive Ereignisse ({len(active)})")
m = build_map(active, stations, ubahn_geojson)
st_folium(m, width="100%", height=520, returned_objects=[])

st.divider()

# ── Active table ──────────────────────────────────────────────────────────────

st.subheader("Aktive Kontrollen")
if active.empty:
    st.success("Keine aktiven Ereignisse — alles ruhig.")
else:
    display_cols = [c for c in ["ereignis_typ", "PartitionKey", "linie", "ort", "zusammenfassung", "konfidenz", "gestartet_am"] if c in active.columns]
    st.dataframe(
        active[display_cols].rename(columns={"PartitionKey": "Kategorie", "ereignis_typ": "Ereignistyp"}),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── Closed table ──────────────────────────────────────────────────────────────

st.subheader("Abgeschlossene Ereignisse")
if closed.empty:
    st.info("Noch keine abgeschlossenen Ereignisse.")
else:
    display_cols = [c for c in ["ereignis_typ", "PartitionKey", "linie", "ort", "zusammenfassung", "gestartet_am", "beendet_am"] if c in closed.columns]
    st.dataframe(
        closed[display_cols].rename(columns={"PartitionKey": "Kategorie", "ereignis_typ": "Ereignistyp"}),
        use_container_width=True,
        hide_index=True,
    )
