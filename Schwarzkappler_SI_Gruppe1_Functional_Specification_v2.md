# Systems Integration — Functional Specification
## SchwarzkapplerRadar — Ticketkontroll-Alert System Wien
**FHTW Wirtschaftsinformatik | SS 2025**
**Systems Integration — VZ 1**

---

## 1 Summary

FareRadar is a real-time integration platform that monitors the public Telegram group *schwarzkappler.info Wien* for fare inspection (Ticketkontrolle) reports in the Vienna public transport network.

User-submitted free-text messages are automatically extracted via the Telegram MTProto TCP protocol using the Telethon library, interpreted by a Large Language Model (LLM) hosted on Azure AI Foundry, and transformed into structured event records. These structured events are persisted in Azure Table Storage (cloud-native). A Streamlit-based web dashboard displays all active and past inspection events as a live event feed, a filterable data table, and an interactive map with station pins derived from the official Wiener Linien station dataset.

The backend listener (`main-azure.py`) and the frontend dashboard (`app.py`) run as two independent processes. The backend writes to Azure Table Storage; the frontend reads from it. All credentials are stored in a `.env` file and never committed to version control.

---

## 2 Stakeholders

All team members contribute equally across all areas of the project. No fixed role assignments are made.

| Name | Notes |
|---|---|
| El Roumi Mohamed | Team member — all areas |
| Wimmer Andreas | Team member — all areas |
| Lutz Clemens Werner | Team member — all areas |
| Lin Hao | Team member — all areas |
| Serloth-Schwarzer Markus | Team member — all areas |

---

## 3 Functional Overview

The system consists of four logical layers communicating in a unidirectional pipeline.

### 3.1 Architecture Overview

| Layer | Component | Technology | Location |
|---|---|---|---|
| Input | Telegram MTProto Client | Telethon / MTProto TCP | localhost |
| Input Source | schwarzkappler.info Wien | Public Telegram group | External |
| Processing | Python Backend | Python 3.x + asyncio | localhost |
| Intelligence | LLM API | Azure AI Foundry (OpenAI-compatible) | External (Azure) |
| Persistence | Azure Table Storage | azure-data-tables / HTTPS | External (Azure) |
| Presentation | Streamlit Dashboard | Streamlit + Folium | localhost |

### 3.2 Telegram Integration — MTProto TCP

FareRadar uses the MTProto TCP protocol via the Telethon Python library. This provides event-based push delivery from the Telegram server without polling.

| Property | Value |
|---|---|
| Protocol | MTProto 2.0 over TCP |
| Library | telethon (Python) |
| Authentication | Telegram user account — api_id + api_hash from my.telegram.org |
| Session | fareradar.session (cached locally — no repeated login) |
| Monitored Group | schwarzkappler.info Wien (public Telegram group) |
| Delivery Model | Event-based push — NewMessage handler fires on each new message |
| Group membership | Not required — public group accessible via username directly |

### 3.3 Data Flow

The pipeline executes the following steps for each incoming Telegram message:

**Step 1 — Receive:** The Telethon MTProto client receives a `NewMessage` event from *schwarzkappler.info Wien*, pushed directly by the Telegram server via TCP. No polling loop is required.

**Step 2 — Filter:** The async event handler discards non-text messages before forwarding to the LLM.

**Step 3 — Extract:** The raw message text is sent to the Azure AI Foundry LLM endpoint with a structured system prompt. The LLM returns a JSON object conforming to the defined event schema, enforced via `response_format: json_object`.

**Step 4 — Validate & Enrich:** The JSON response is parsed and enriched with `gestartet_am` (message timestamp) and `beendet_am` (empty string — open event).

**Step 5 — Persist:** The structured event is written to Azure Table Storage (`kontrollen` table). If `ereignis_typ` is `Ende`, the backend queries for an existing open event matching `kategorie`, `linie`, and `ort`, and closes it by setting `beendet_am`.

**Step 6 — Display:** The Streamlit dashboard reads from Azure Table Storage on a 30-second cache cycle and re-renders the map and tables automatically.

---

## 4 Involved Systems

### System 1 — Telegram MTProto Client (Telethon)

Role: Primary data source.

| Property | Value |
|---|---|
| Protocol | MTProto 2.0 over TCP |
| Library | telethon |
| Authentication | Telegram user account (api_id + api_hash) |
| Session file | fareradar.session |
| Monitored group | schwarzkappler.info Wien |

### System 2 — Azure AI Foundry (LLM)

Role: Intelligence layer. Transforms unstructured free-text into structured JSON events.

| Property | Value |
|---|---|
| Protocol | HTTPS REST (OpenAI-compatible) |
| Deployment | gpt-5-mini (via Azure AI Foundry project endpoint) |
| Direction | Outbound only |
| Authentication | API Key (AZURE_AI_FOUNDRY_KEY) |
| Response Format | JSON object enforced via response_format parameter |

### System 3 — Azure Table Storage

Role: Primary persistent storage. Cloud-native, serverless, schema-flexible key-value store.

| Property | Value |
|---|---|
| Service | Azure Table Storage |
| Library | azure-data-tables |
| Table name | kontrollen |
| PartitionKey | kategorie (e.g. Kontrolle, Unfall, Stau, Sonstiges) |
| RowKey | Sanitised ISO timestamp of the event |
| Authentication | Connection String (AZURE_STORAGE_CONNECTION_STRING) |

### System 4 — Streamlit Dashboard

Role: Frontend. Reads from Azure Table Storage and renders a live dashboard.

| Property | Value |
|---|---|
| Framework | Streamlit |
| Map library | Folium + streamlit-folium |
| Station data | wienerlinien-ogd-haltestellen.csv (official Wiener Linien dataset) |
| Station matching | Fuzzy matching via rapidfuzz (threshold: 70 WRatio score) |
| Data refresh | 30-second TTL cache (st.cache_data) + manual refresh button |
| Filters | Sidebar — filter by Linie and Kategorie |

---

## 5 Event Schema

The following fields define the structure of an event as produced by the LLM and stored in Azure Table Storage:

| Field | Type | Description |
|---|---|---|
| PartitionKey | string | Kategorie: Kontrolle / Unfall / Stau / Sonstiges |
| RowKey | string | Sanitised ISO timestamp (unique identifier) |
| wichtig | boolean | Whether the event is flagged as important by the LLM |
| kategorie | string | Kontrolle / Unfall / Stau / Sonstiges |
| ereignis_typ | string | Beginn / Ende / Einzelmeldung |
| linie | string | Line number (e.g. U1, 13A) or empty |
| ort | string | Station name (e.g. Stephansplatz) or empty |
| zusammenfassung | string | One-sentence summary generated by the LLM |
| konfidenz | float (0–1) | LLM certainty score |
| gestartet_am | ISO datetime string | Timestamp of the original Telegram message |
| beendet_am | string | Empty while active; ISO timestamp when closed |

### 5.1 Event Lifecycle

| State | Condition |
|---|---|
| Open (active) | `beendet_am == ""` |
| Closed manually | Follow-up message with `ereignis_typ = Ende` matched and closed by backend |
| Closed automatically | `gestartet_am` older than `AUTO_CLOSE_MINUTES` — closed by background task |

### 5.2 Auto-Close Logic

Not every inspection report will be followed by an explicit end message. The backend runs a background asyncio task that wakes every 60 seconds and closes any open event older than the configured threshold.

| Setting | Location | Default | Notes |
|---|---|---|---|
| `AUTO_CLOSE_MINUTES` | Top of `main-azure.py` | 90 | Change to 1–3 for live demo |
| `CHECK_INTERVAL_SECONDS` | Top of `main-azure.py` | 60 | How often the cleanup loop runs |

The auto-close task sets `beendet_am` to the current UTC timestamp and logs which events were closed to the terminal.

---

## 6 Use Cases

### UC-01: Neue Kontrolle erfassen

| Property | Detail |
|---|---|
| Purpose | Detect and record a new fare inspection from a Telegram message |
| Trigger | New message pushed to Telethon handler from schwarzkappler.info Wien |
| Involved Systems | Telegram MTProto Client, Python Backend, Azure AI Foundry, Azure Table Storage |
| Input | Free-text (e.g. *Kontrolleur bei Stephansplatz, U1*) |
| LLM Output | `{ kategorie: Kontrolle, linie: U1, ort: Stephansplatz, ereignis_typ: Einzelmeldung, konfidenz: 0.93 }` |
| Result | New record created in Azure Table Storage; red pin appears on Streamlit map |

### UC-02: Kontrolle als beendet markieren

| Property | Detail |
|---|---|
| Purpose | Close an existing active event when the inspection ends |
| Trigger | Follow-up message (e.g. *keine Kontrolle mehr, Stephansplatz*) |
| Involved Systems | Telegram MTProto Client, Python Backend, Azure AI Foundry, Azure Table Storage |
| Logic | LLM returns `ereignis_typ: Ende`; backend queries for open event matching linie + ort; sets `beendet_am` |
| Result | Event closed in Azure Table Storage; pin disappears from active map |

### UC-03: Automatisches Ablaufen (Auto-Close)

| Property | Detail |
|---|---|
| Purpose | Automatically close events that receive no explicit end confirmation |
| Trigger | asyncio background task wakes every `CHECK_INTERVAL_SECONDS` |
| Involved Systems | Python Backend, Azure Table Storage |
| Logic | Query all open events; close those where `gestartet_am` < now − `AUTO_CLOSE_MINUTES` |
| Result | Events closed automatically; Streamlit dashboard updates on next 30s cache refresh |

### UC-04: Dashboard anzeigen

| Property | Detail |
|---|---|
| Purpose | Display live event map, active controls table, and closed events |
| Trigger | User opens the Streamlit app in the browser (`streamlit run app.py`) |
| Involved Systems | Streamlit, Azure Table Storage, wienerlinien-ogd-haltestellen.csv |
| Map | Folium map centred on Vienna; pins colour-coded by kategorie |
| Station matching | `ort` from LLM fuzzy-matched to `PlatformText` in CSV to obtain coordinates |
| Filters | Sidebar filters by Linie and Kategorie; manual refresh button |
| Refresh | Data cached for 30 seconds; automatic re-render on cache expiry |

---

## 7 Non-Functional Requirements

| Category | Requirement |
|---|---|
| Deployment | Backend and frontend run as two separate local processes; Azure used for storage and LLM only |
| Availability | System is operational while both Python processes are running; no 24/7 SLA required |
| Latency | New events appear in the dashboard within ~30 seconds (MTProto push < 1s + processing + Streamlit cache cycle) |
| Security | All credentials stored in `.env` and `fareradar.session`; never committed to version control |
| Configurability | Auto-close timeout adjustable via `AUTO_CLOSE_MINUTES` constant in `main-azure.py` without restarting Streamlit |
| Data Retention | Azure Table Storage persists all events across process restarts |

---

## 8 Technology Stack

| Component | Technology | Package |
|---|---|---|
| Backend Language | Python 3.x + asyncio | — |
| Telegram Integration | MTProto TCP via Telethon | telethon |
| LLM Integration | Azure AI Foundry (OpenAI-compatible) | openai >= 1.0 |
| Cloud Storage | Azure Table Storage | azure-data-tables |
| Frontend Dashboard | Streamlit | streamlit |
| Map Visualisation | Folium + streamlit-folium | folium, streamlit-folium |
| Station Fuzzy Matching | RapidFuzz | rapidfuzz |
| Station Dataset | Wiener Linien OGD Haltestellen CSV | — |
| Configuration | Environment Variables + Session File | python-dotenv, telethon session |

---

## 9 File Overview

| File | Purpose |
|---|---|
| `main-azure.py` | Backend: Telegram listener, LLM analysis, Azure Table Storage writer, auto-close task |
| `app.py` | Frontend: Streamlit dashboard with map, tables, and sidebar filters |
| `wienerlinien-ogd-haltestellen.csv` | Station reference dataset (name → coordinates) |
| `.env` | Credentials: Telegram, Azure AI Foundry, Azure Storage (not committed) |
| `fareradar.session` | Telethon session cache (not committed) |
| `requirements.txt` | Python dependencies |
