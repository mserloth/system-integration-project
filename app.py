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
    """Lädt die U-Bahn-Streckendaten vom Wiener Open-Data-WFS als GeoJSON.

    Ruft den Web Feature Service (WFS) der Stadt Wien ab und gibt die
    vollständige GeoJSON-Antwort mit allen U-Bahn-Liniengeometrien zurück.
    Das Ergebnis wird von Streamlit 1 Stunde lang gecacht (ttl=3600 s),
    um wiederholte Netzwerkanfragen zu vermeiden.

    Returns:
        dict: GeoJSON-Objekt mit allen U-Bahn-Features (Geometrien + Properties),
              oder None wenn der Abruf fehlschlägt (Timeout, Netzwerkfehler, etc.).

    Note:
        Die Koordinaten liegen im Format [Longitude, Latitude] (EPSG:4326).
        Für Folium müssen sie beim Zeichnen zu [Latitude, Longitude] umgekehrt
        werden — siehe draw_ubahn_lines().
    """
    try:
        import json
        with urllib.request.urlopen(_WFS_URL, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def draw_ubahn_lines(m: folium.Map, active_lines: set, geojson: dict | None):
    """Zeichnet die U-Bahn-Streckenlinien als farbige PolyLines auf die Folium-Karte.

    Iteriert über alle GeoJSON-Features des Wiener WFS, filtert auf die aktuell
    relevanten Linien (active_lines) und zeichnet jede Strecke in der offiziellen
    Wiener Linien-Farbe. Features ohne passenden LINFO-Eintrag oder ohne aktives
    Ereignis werden übersprungen.

    Args:
        m (folium.Map): Die Folium-Karte, auf die die Linien gezeichnet werden.
        active_lines (set): Set mit Liniennamen (z.B. {"U3", "U6"}), die gezeichnet
                            werden sollen — abgeleitet aus den aktiven Ereignissen.
        geojson (dict | None): GeoJSON-Objekt vom Wiener WFS (siehe load_ubahn_geojson()).
                               Bei None wird die Funktion ohne Aktion beendet.

    Note:
        GeoJSON speichert Koordinaten als [Longitude, Latitude] — Folium erwartet
        [Latitude, Longitude]. Die Umkehrung erfolgt via [[c[1], c[0]] for c in coords].
    """
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
    """Lädt die Wiener Linien Haltestellendaten aus der lokalen CSV-Datei.

    Liest die offizielle OGD-Haltestellenliste der Wiener Linien ein und gibt
    nur die für die Kartenverortung relevanten Spalten zurück. Duplikate beim
    Haltestellennamen (PlatformText) werden entfernt, da derselbe Name durch
    mehrere Linien mehrfach vorkommen kann. Das Ergebnis wird 30 Sekunden
    gecacht (ttl=30 s).

    Returns:
        pd.DataFrame: DataFrame mit den Spalten PlatformText, Longitude, Latitude —
                      eine Zeile pro eindeutigem Haltestellennamen.
    """
    df = pd.read_csv(CSV_PATH, sep=";")
    return df[["PlatformText", "Longitude", "Latitude"]].drop_duplicates("PlatformText")


@st.cache_data(ttl=30)
def load_events() -> pd.DataFrame:
    """Lädt alle Ereignisse aus der Azure Table Storage Tabelle 'kontrollen'.

    Verbindet sich über den konfigurierten Connection String mit Azure Table Storage
    und liest alle Entitäten der Tabelle 'kontrollen' aus. Fehlende Werte in der
    Spalte 'beendet_am' werden mit leerem String befüllt, um die spätere Filterung
    in aktive/abgeschlossene Ereignisse zu vereinfachen. Das Ergebnis wird 30
    Sekunden gecacht (ttl=30 s).

    Returns:
        pd.DataFrame: DataFrame mit allen Ereignissen (Kontrollen, Unfälle, etc.),
                      oder ein leerer DataFrame wenn keine Einträge vorhanden sind.

    Note:
        Aktive Ereignisse haben beendet_am == "", abgeschlossene haben einen
        Zeitstempel. Diese Unterscheidung wird in build_map() genutzt.
    """
    svc = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    client = svc.get_table_client("kontrollen")
    rows = list(client.list_entities())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["beendet_am"] = df.get("beendet_am", "").fillna("")
    return df


def fuzzy_coords(ort: str, stations: pd.DataFrame):
    """Ermittelt GPS-Koordinaten für einen Ortstext per unscharfer Suche (Fuzzy Matching).

    Vergleicht den freien Ortstext (z.B. aus einer Telegram-Meldung) mit allen
    bekannten Haltestellennamen und gibt die Koordinaten der besten Übereinstimmung
    zurück. Verwendet rapidfuzz WRatio-Scoring, das Tippfehler, Abkürzungen und
    abweichende Schreibweisen toleriert. Treffer unter 70 % Ähnlichkeit werden
    als zu unsicher verworfen.

    Args:
        ort (str): Freitext-Ortsangabe, z.B. "Karlsplatz" oder "Praterstern U".
        stations (pd.DataFrame): Haltestellendaten aus load_stations() mit den
                                  Spalten PlatformText, Latitude, Longitude.

    Returns:
        tuple[float, float]: (Latitude, Longitude) der besten Übereinstimmung,
                             oder (None, None) bei leerem Input, leerem DataFrame
                             oder zu geringer Übereinstimmung (< 70 %).
    """
    if not ort or stations.empty:
        return None, None
    result = process.extractOne(ort, stations["PlatformText"], scorer=fuzz.WRatio)
    if result is None or result[1] < 70:
        return None, None
    row = stations[stations["PlatformText"] == result[0]].iloc[0]
    return float(row["Latitude"]), float(row["Longitude"])


def build_map(active: pd.DataFrame, stations: pd.DataFrame, geojson: dict | None) -> folium.Map:
    """Erstellt die interaktive Folium-Karte mit U-Bahn-Linien und Ereignis-Markern.

    Baut eine auf Wien zentrierte Karte auf, zeichnet die relevanten U-Bahn-Strecken
    (nur Linien mit aktiven Ereignissen) und setzt für jedes aktive Ereignis einen
    farbigen Marker an die per Fuzzy-Matching ermittelte Haltestellenposition.
    Ereignisse ohne zuordenbare Koordinaten werden stillschweigend übersprungen.

    Args:
        active (pd.DataFrame): Gefilterte aktive Ereignisse aus load_events(),
                               enthält Spalten: ort, linie, PartitionKey, zusammenfassung.
        stations (pd.DataFrame): Haltestellendaten aus load_stations() für die
                                  Koordinaten-Auflösung per fuzzy_coords().
        geojson (dict | None): U-Bahn-Streckengeometrien aus load_ubahn_geojson()
                               für draw_ubahn_lines().

    Returns:
        folium.Map: Fertig befüllte Karte mit Linien und Markern, bereit für
                    die Darstellung via st_folium().

    Note:
        Marker-Farben werden über KATEGORIE_COLOR gesteuert (rot=Kontrolle,
        orange=Unfall, blau=Stau, grau=Sonstiges).
    """
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
