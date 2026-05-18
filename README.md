# SchwarzkapplerRadar - Wiener Linien Fahrkartenkontrolle Monitor

> Echtzeit-Monitoring-System für Fahrkartenkontroll-Meldungen der Wiener Linien, basierend auf Telegram, Azure AI Foundry und Azure Table Storage.

---

## Inhaltsverzeichnis

- [Projektübersicht](#projektübersicht)
- [Systemarchitektur](#systemarchitektur)
- [Features](#features)
- [Technologie-Stack](#technologie-stack)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Starten der Anwendung](#starten-der-anwendung)
- [Projektstruktur](#projektstruktur)
- [Datenmodell](#datenmodell)
- [Datenfluss](#datenfluss)
- [Dashboard-Übersicht](#dashboard-übersicht)
- [Konfigurationsparameter](#konfigurationsparameter)
- [Alternativer Betrieb mit lokalem LLM](#alternativer-betrieb-mit-lokalem-llm)

---

## Projektübersicht

**SchwarzkapplerRadar** ist ein cloudbasiertes Echtzeit-Monitoring-System, das automatisch Fahrkartenkontroll-Meldungen aus der öffentlichen Telegram-Gruppe [schwarzkappler.info Wien](https://t.me/schwarzkappler) erfasst, mittels Azure AI strukturiert verarbeitet und auf einem interaktiven Web-Dashboard visualisiert.

Das System wurde im Rahmen des Kurses **Systems Integration (SS 2025)** an der [FH Technikum Wien (FHTW)](https://www.technikum-wien.at/) entwickelt.

**Kern-Workflow:**
1. Nutzer melden Fahrkartenkontroller in der Telegram-Gruppe
2. Das Backend empfängt Nachrichten in Echtzeit (Telethon MTProto)
3. Azure AI Foundry (GPT-5-mini) extrahiert strukturierte Daten aus Freitext
4. Ereignisse werden in Azure Table Storage persistiert
5. Das Streamlit-Dashboard zeigt alle aktiven Meldungen auf einer interaktiven Karte

---

## Systemarchitektur

<img width="938" height="827" alt="image" src="https://github.com/user-attachments/assets/bf3bf046-283b-4f70-a40c-bacbc2e896a2" />

---

## Features

- **Echtzeit-Telegram-Listener** — Empfängt Nachrichten sofort über MTProto (kein Polling-Delay)
- **KI-gestützte Datenextraktion** — Azure GPT-5-mini extrahiert Linie, Station, Kategorie und Konfidenz aus Freitext-Nachrichten
- **Persistente Cloud-Speicherung** — Alle Ereignisse werden in Azure Table Storage gespeichert
- **Interaktive Karte** — Folium-Karte mit Wien-Zentrierung, farblich nach Kategorie kodiert
- **Fuzzy-Stationssuche** — RapidFuzz-Matching gegen den offiziellen Wiener-Linien-Datensatz (9.000+ Stationen)
- **Live-Dashboard** — Streamlit-App mit 30-Sekunden-Auto-Refresh, Filter nach Linie und Kategorie
- **Auto-Close-Mechanismus** — Ereignisse werden automatisch nach konfigurierbarem Timeout geschlossen
- **Manuelles Schließen** — Follow-up-Meldungen mit `ereignis_typ = "Ende"` schließen offene Ereignisse

---

## Technologie-Stack

| Bereich | Technologie | Zweck |
|---------|-------------|-------|
| **Messaging** | Telethon (MTProto) | Telegram-Listener |
| **AI/LLM** | Azure AI Foundry (gpt-5-mini) | JSON-Extraktion aus Freitext |
| **Storage** | Azure Table Storage | Persistenz der Ereignisse |
| **Frontend** | Streamlit | Web-Dashboard |
| **Karte** | Folium + streamlit-folium | Interaktive Kartenvisualisierung |
| **Fuzzy-Matching** | RapidFuzz | Stationsname-Auflösung |
| **Daten** | Pandas | CSV-Verarbeitung (WL-Stationsdaten) |
| **API-Client** | openai SDK | Azure-kompatible LLM-Aufrufe |
| **Config** | python-dotenv | Umgebungsvariablen |

---

## Voraussetzungen

- **Python** 3.9 oder höher
- **Telegram-Account** mit aktivierter API (api_id + api_hash von [my.telegram.org](https://my.telegram.org))
- **Azure-Subscription** mit:
  - Azure AI Foundry Deployment (gpt-5-mini oder kompatibel)
  - Azure Storage Account mit Table Storage
- `pip` oder `pip3` für die Paketinstallation

---

## Installation

### 1. Repository klonen

```bash
git clone https://github.com/mserloth/system-integration-project.git
cd system-integration-project
```

### 2. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

### 3. Umgebungsvariablen konfigurieren

Eine `.env`-Datei im Projektverzeichnis anlegen (Vorlage siehe [Konfiguration](#konfiguration)):

```bash
cp .env.example .env   # falls vorhanden
# oder manuell erstellen:
```

```env
# .env
TELEGRAM_API_ID=deine_api_id
TELEGRAM_API_HASH=dein_api_hash
TARGET_GROUP=-100xxxxxxxxxx

AZURE_AI_FOUNDRY_KEY=dein_azure_key
AZURE_AI_FOUNDRY_ENDPOINT=https://dein-resource.services.ai.azure.com/...
AZURE_AI_FOUNDRY_DEPLOYMENT=gpt-5-mini

AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
```

> **Sicherheitshinweis:** Die `.env`-Datei ist in `.gitignore` eingetragen und wird **nicht** in das Repository eingecheckt. Niemals echte Credentials committen.

---

## Konfiguration

### Pflichtfelder

| Variable | Beschreibung | Wo zu finden |
|----------|-------------|--------------|
| `TELEGRAM_API_ID` | Telegram App ID | [my.telegram.org](https://my.telegram.org) → API development tools |
| `TELEGRAM_API_HASH` | Telegram App Hash | [my.telegram.org](https://my.telegram.org) → API development tools |
| `TARGET_GROUP` | Telegram Gruppen-ID (negativ) | Mit `InitialSetupForGroupID.py` ermitteln |
| `AZURE_AI_FOUNDRY_KEY` | API-Key für Azure AI Foundry | Azure Portal → AI Foundry → Keys |
| `AZURE_AI_FOUNDRY_ENDPOINT` | Endpoint-URL | Azure Portal → AI Foundry → Endpoint |
| `AZURE_AI_FOUNDRY_DEPLOYMENT` | Name des Deployments | Azure Portal → AI Foundry → Deployments |
| `AZURE_STORAGE_CONNECTION_STRING` | Connection String für Azure Storage | Azure Portal → Storage Account → Access Keys |

### Gruppen-ID ermitteln

Die `TARGET_GROUP`-ID einer Telegram-Gruppe ermittelt man einmalig mit dem Hilfsprogramm:

```bash
python InitialSetupForGroupID.py
```

Das Skript gibt alle Chats mit ihren IDs aus. Die gesuchte Gruppe (z. B. `schwarzkappler Test`) hat eine negative ID (z. B. `-1001234567890`).

---

## Starten der Anwendung

Das System besteht aus zwei unabhängigen Prozessen, die **gleichzeitig** in separaten Terminals laufen müssen.

### Terminal 1 — Backend (Telegram-Listener)

```bash
python main-azure.py
```

**Was passiert:**
- Verbindet sich mit Telegram (erster Start: Authentifizierung via SMS/App-Code)
- Lauscht in Echtzeit auf neue Nachrichten in der konfigurierten Gruppe
- Sendet jede Nachricht an Azure AI für JSON-Extraktion
- Schreibt strukturierte Ereignisse in Azure Table Storage
- Startet Background-Task: prüft alle 60 Sekunden auf abgelaufene Ereignisse

**Erwartete Ausgabe:**
```
[2025-05-18 10:30:45] Starte Telegram-Listener...
[2025-05-18 10:30:46] Verbunden mit schwarzkappler.info Wien
[2025-05-18 10:35:12] Neue Meldung von @user123: "Kontrolle U3 Kardinal-Nagl-Platz"
[2025-05-18 10:35:13] Ereignis gespeichert: Kontrolle | U3 | Kardinal-Nagl-Platz | Konfidenz: 0.95
```

### Terminal 2 — Frontend (Streamlit Dashboard)

```bash
streamlit run app.py
```

**Dashboard öffnen:** [http://localhost:8501](http://localhost:8501)

**Was zu sehen ist:**
- Interaktive Karte mit allen aktiven Meldungen als farbige Marker
- Tabelle der aktiven Ereignisse
- Tabelle der abgeschlossenen Ereignisse
- Sidebar-Filter nach Linie und Kategorie
- Automatischer Refresh alle 30 Sekunden

---

## Projektstruktur

```
system-integration-project/
│
├── main-azure.py                          # Primäres Backend (Produktion)
│   └─ Telegram-Listener + Azure AI + Auto-Close Task
│
├── app.py                                 # Streamlit Frontend-Dashboard
│   └─ Karte, Tabellen, Filter, Auto-Refresh
│
├── main.py                                # Einfacher Listener (Debugging, kein LLM)
│
├── llm-setup.py                           # Ollama lokales LLM (Alternative)
├── main-setupTest-json.py                 # Erweitertes lokales LLM mit vollem Schema
│
├── InitialSetupForGroupID.py              # Einmalig: Telegram Gruppen-ID ermitteln
│
├── requirements.txt                       # Python-Abhängigkeiten
├── .env                                   # Credentials (NICHT in Git!)
├── .gitignore                             # Schließt .env, *.session aus
│
├── wienerlinien-ogd-haltestellen.csv      # Referenzdaten: 9.000+ Wiener Stationen
│                                          # Quelle: Open Data Österreich
│
├── Schwarzkappler_SI_Gruppe1_Functional_Specification_v2.md   # Funktionale Spezifikation
└── Schwarzkappler_SI_Gruppe1_Functional_Specification_v2.docx # Selbes Dokument als Word
```

---

## Datenmodell

Ereignisse werden in der Azure Table Storage Tabelle **`kontrollen`** gespeichert.

| Feld | Typ | Beispiel | Beschreibung |
|------|-----|---------|--------------|
| `PartitionKey` | string | `"Kontrolle"` | Fester Wert für Table-Partitionierung |
| `RowKey` | string | `"2025-05-18T10-30-45p00_00_UTC"` | Sanitierter Timestamp (eindeutige ID) |
| `wichtig` | boolean | `true` | LLM-Relevanz-Flag |
| `kategorie` | string | `"Kontrolle"` / `"Unfall"` / `"Stau"` / `"Sonstiges"` | Ereigniskategorie |
| `ereignis_typ` | string | `"Beginn"` / `"Ende"` / `"Einzelmeldung"` | Art der Meldung |
| `linie` | string | `"U1"`, `"13A"`, `"D"` | Betroffene Linie |
| `ort` | string | `"Stephansplatz"` | Stationsname |
| `zusammenfassung` | string | `"Kontrolle bei Stephansplatz U1"` | Ein-Satz-Zusammenfassung (LLM) |
| `konfidenz` | float | `0.0` – `1.0` | LLM-Konfidenzwert |
| `gestartet_am` | ISO-datetime | `"2025-05-18T10:30:45+00:00"` | Zeitstempel der Original-Nachricht |
| `beendet_am` | string | `""` (aktiv) / ISO-datetime (geschlossen) | Leer = aktiv, befüllt = abgeschlossen |

### Ereignis-Lebenszyklus

```
Neue Nachricht
    │
    ▼
Ereignis erstellt (beendet_am = "")
    │
    ├── Follow-up "Ende"-Meldung ──▶ beendet_am = Timestamp (manuell)
    │
    └── Kein Follow-up nach X Min. ──▶ beendet_am = Timestamp (Auto-Close)
```

---

## Datenfluss

```
1. Telegram-Nachricht eingeht (z. B. "Kontrolle U3 Erdberg, gerade gesehen")
         │
         ▼
2. Telethon empfängt Nachricht via MTProto (main-azure.py)
         │
         ▼
3. Azure AI Foundry (gpt-5-mini) verarbeitet Freitext → JSON:
   {
     "wichtig": true,
     "kategorie": "Kontrolle",
     "ereignis_typ": "Einzelmeldung",
     "linie": "U3",
     "ort": "Erdberg",
     "zusammenfassung": "Fahrkartenkontrolle bei U3 Erdberg",
     "konfidenz": 0.92
   }
         │
         ▼
4. Python-Backend validiert & fügt Timestamps hinzu
         │
         ▼
5. Azure Table Storage speichert Ereignis in Tabelle "kontrollen"
         │
         ▼
6. Streamlit (app.py) liest alle 30 Sekunden neue Daten
         │
         ▼
7. RapidFuzz matched "Erdberg" → Koordinaten aus WL-CSV
         │
         ▼
8. Folium-Marker auf Karte gesetzt, Tabellen aktualisiert
         │
         ▼
9. Background-Task prüft alle 60 Sek. → schließt ältere Ereignisse automatisch
```

---

## Dashboard-Übersicht

Das Streamlit-Dashboard unter [http://localhost:8501](http://localhost:8501) bietet:

| Bereich | Beschreibung |
|---------|-------------|
| **Karte** | Interaktive Folium-Karte zentriert auf Wien; Marker farblich nach Kategorie (Rot = Kontrolle, Gelb = Stau, Blau = Sonstiges) |
| **Aktive Ereignisse** | Tabelle mit allen offenen Meldungen (beendet_am leer) |
| **Abgeschlossene Ereignisse** | Historische Tabelle aller geschlossenen Meldungen |
| **Sidebar-Filter** | Filterung nach Linie (z. B. "U1", "13A") und Kategorie |
| **Auto-Refresh** | Alle 30 Sekunden automatische Aktualisierung aus Azure Storage |

---

## Konfigurationsparameter

In `main-azure.py` sind folgende Konstanten anpassbar:

| Parameter | Standard | Beschreibung |
|-----------|---------|-------------|
| `AUTO_CLOSE_MINUTES` | `90` | Minuten bis ein aktives Ereignis automatisch geschlossen wird |
| `CHECK_INTERVAL_SECONDS` | `60` | Intervall des Auto-Close-Background-Tasks in Sekunden |

**Für Demo/Testing:** `AUTO_CLOSE_MINUTES = 5` setzt Ereignisse schnell auf "abgeschlossen".

---

## Alternativer Betrieb mit lokalem LLM

Als Alternative zu Azure AI Foundry kann Ollama (lokales LLM) verwendet werden:

### Voraussetzungen

1. [Ollama](https://ollama.com) installieren
2. Modell herunterladen: `ollama pull llama3` (oder kompatibles Modell)
3. Ollama starten: `ollama serve`

### Starten mit lokalem LLM

```bash
python llm-setup.py
# oder mit erweitertem Schema:
python main-setupTest-json.py
```

> **Hinweis:** Die lokale Variante eignet sich für Offline-Entwicklung und Tests, liefert aber möglicherweise schlechtere Extraktionsqualität als der Azure-Dienst.

---

## Entwicklung & Tests

### Einfacher Listener ohne LLM (Debugging)

```bash
python main.py
```

Gibt eingehende Nachrichten direkt aus, ohne LLM-Verarbeitung oder Speicherung — nützlich zum Testen der Telegram-Verbindung.

### Gruppen-ID ermitteln

```bash
python InitialSetupForGroupID.py
```

Listet alle verfügbaren Telegram-Chats mit IDs auf. Einmalig ausführen, um `TARGET_GROUP` zu befüllen.

### Abhängigkeiten

Alle Abhängigkeiten sind in `requirements.txt` mit festen Versionen gepinnt:

```bash
pip install -r requirements.txt
```

Wichtige Pakete:

| Paket | Version | Zweck |
|-------|---------|-------|
| `telethon` | ≥1.36 | Telegram MTProto Client |
| `openai` | ≥1.0 | Azure-kompatibler LLM-Client |
| `azure-data-tables` | ≥12.0 | Azure Table Storage SDK |
| `streamlit` | ≥1.30 | Web-Dashboard Framework |
| `folium` | ≥0.15 | Interaktive Karte |
| `streamlit-folium` | ≥0.16 | Folium-Streamlit-Integration |
| `rapidfuzz` | ≥3.0 | Fuzzy-String-Matching |
| `pandas` | ≥2.0 | CSV-Datenverarbeitung |
| `python-dotenv` | ≥1.0 | .env-Datei-Unterstützung |

---

> **Datenquelle Stationen:** [Wiener Linien Open Data](https://data.gv.at/katalog/dataset/wiener-linien-echtzeitdaten-via-gtfs) — `wienerlinien-ogd-haltestellen.csv`
