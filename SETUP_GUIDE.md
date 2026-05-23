# FareRadar – Setup Guide für Kommilitonen

> **Ziel:** Dieses Dokument erklärt Schritt für Schritt, wie ihr FareRadar lokal zum Laufen bringt.  
> Das System besteht aus zwei Teilen:
> - **`main-azure.py`** → Backend: hört Telegram ab, analysiert Nachrichten mit Azure AI, speichert in Azure Table Storage
> - **`app.py`** → Frontend: Streamlit-Dashboard mit interaktiver Karte

---

## Inhaltsverzeichnis

1. [Voraussetzungen](#1-voraussetzungen)
2. [Repository klonen & Abhängigkeiten installieren](#2-repository-klonen--abhängigkeiten-installieren)
3. [Telegram API einrichten](#3-telegram-api-einrichten)
4. [Azure Storage Account einrichten](#4-azure-storage-account-einrichten)
5. [Azure AI Foundry einrichten](#5-azure-ai-foundry-einrichten)
6. [.env Datei erstellen](#6-env-datei-erstellen)
7. [Erster Start & Session-Authentifizierung](#7-erster-start--session-authentifizierung)
8. [Frontend starten (Streamlit)](#8-frontend-starten-streamlit)
9. [Architekturübersicht](#9-architekturübersicht)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Voraussetzungen

| Tool | Version | Download |
|---|---|---|
| Python | ≥ 3.10 | https://www.python.org/downloads/ |
| Git | beliebig | https://git-scm.com |
| Telegram-Account | — | Telegram-App auf Handy |
| Azure-Account | Student-Account reicht | https://azure.microsoft.com/free/students/ |

> ℹ️ Azure for Students gibt 100 $ Guthaben — das reicht für das Projekt.

---

## 2. Repository klonen & Abhängigkeiten installieren

```bash
git clone https://github.com/mserloth/system-integration-project.git
cd system-integration-project
```

Virtuelle Umgebung erstellen (empfohlen):

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

Pakete installieren:

```bash
pip install -r requirements.txt
```

Installiert werden: `telethon`, `python-dotenv`, `openai`, `azure-data-tables`, `streamlit`, `folium`, `streamlit-folium`, `rapidfuzz`, `streamlit-autorefresh`

---

## 3. Telegram API einrichten

Das Backend verbindet sich als **User-Client** (nicht als Bot) mit Telegram. Jeder braucht eigene API-Zugangsdaten.

### 3.1 API-Zugangsdaten holen

1. Öffne **https://my.telegram.org** im Browser
2. Mit deiner Telegram-Handynummer einloggen (inkl. Ländervorwahl, z.B. `+43...`)
3. Den Code eingeben, den Telegram per SMS/App schickt
4. Klick auf **"API development tools"**
5. Neue App erstellen:
   - **App title:** `FareRadar` (oder beliebig)
   - **Short name:** `fareradar`
   - **Platform:** Other
6. Du bekommst:
   - `App api_id` → das ist deine **TELEGRAM_API_ID** (eine Zahl, z.B. `12345678`)
   - `App api_hash` → das ist dein **TELEGRAM_API_HASH** (ein langer String)

> ⚠️ Diese Daten sind personenbezogen — **nicht teilen**, jeder erstellt seine eigenen!

### 3.2 Der Telegram-Gruppe beitreten

Die Zielgruppe, auf die das System lauscht, hat folgende ID:

```
TARGET_GROUP=-1003925024746
```

Bitte Markus, dich in die Gruppe **„FareRadar Testgruppe"** einzuladen — du musst Mitglied sein, damit `telethon` die Nachrichten empfangen kann.

---

## 4. Azure Storage Account einrichten

Azure Table Storage speichert alle erkannten Kontrollereignisse.

### 4.1 Resource Group erstellen (falls noch nicht vorhanden)

1. Öffne **https://portal.azure.com**
2. Suche oben: **„Resource groups"** → **„+ Create"**
3. Einstellungen:
   - **Subscription:** dein Student-Account
   - **Resource group name:** `fareradar-rg`
   - **Region:** `West Europe` (für Wien am nächsten)
4. **„Review + create"** → **„Create"**

### 4.2 Storage Account erstellen

1. Suche im Portal: **„Storage accounts"** → **„+ Create"**
2. Einstellungen:

   | Feld | Wert |
   |---|---|
   | Resource group | `fareradar-rg` |
   | Storage account name | z.B. `fareradarstorage` (muss global eindeutig sein!) |
   | Region | `West Europe` |
   | Performance | Standard |
   | Redundancy | LRS (Locally Redundant — günstigste Option) |

3. **„Review + create"** → **„Create"**

### 4.3 Tabelle erstellen

1. Öffne den neu erstellten Storage Account
2. Im linken Menü: **„Tables"** (unter „Data storage")
3. Klick **„+ Table"**
4. **Table name:** `kontrollen` ← **genau so schreiben, Kleinbuchstaben!**
5. **„OK"**

### 4.4 Connection String kopieren

1. Im Storage Account → linkes Menü: **„Access keys"** (unter „Security + networking")
2. Klick **„Show"** bei key1
3. Kopiere den kompletten **„Connection string"** — sieht so aus:

```
DefaultEndpointsProtocol=https;AccountName=fareradarstorage;AccountKey=DEIN_KEY_HIER==;EndpointSuffix=core.windows.net
```

→ Das ist dein **AZURE_STORAGE_CONNECTION_STRING**

---

## 5. Azure AI Foundry einrichten

Das Backend schickt Telegram-Texte an ein GPT-Modell zur strukturierten Analyse.

### 5.1 Azure AI Foundry Hub & Projekt erstellen

1. Öffne **https://ai.azure.com**
2. Klick **„+ New project"**
3. Einstellungen:
   - **Project name:** z.B. `fareradar-ai`
   - **Hub:** neuen Hub erstellen → Name z.B. `fareradar-hub`, Region `Sweden Central` (dort sind GPT-Modelle verfügbar)
4. **„Create"** — das dauert ~1–2 Minuten

### 5.2 Modell deployen

1. Im Projekt → linkes Menü: **„Models + endpoints"** → **„+ Deploy model"** → **„Deploy base model"**
2. Modell auswählen: **`gpt-4o-mini`** (günstig, schnell, reicht für unser Use Case)
3. **Deployment name:** `gpt-4o-mini` (merken — das ist später dein `AZURE_AI_FOUNDRY_DEPLOYMENT`)
4. **„Deploy"**

> ℹ️ Das Deployment kann 1–3 Minuten dauern.

### 5.3 Endpoint & Key kopieren

1. Im Projekt → **„Models + endpoints"** → auf dein Deployment klicken
2. Kopiere:
   - **Target URI / Endpoint** → sieht so aus:
     ```
     https://DEIN-RESOURCE-NAME.services.ai.azure.com/api/projects/DEIN-PROJEKT/openai/v1
     ```
     → das ist dein **AZURE_AI_FOUNDRY_ENDPOINT**
   - **Key** → das ist dein **AZURE_AI_FOUNDRY_KEY**

---

## 6. .env Datei erstellen

Erstelle im Projektordner eine Datei namens `.env` (kein Dateiname davor, nur `.env`):

```bash
# Windows (PowerShell)
New-Item .env -ItemType File

# macOS / Linux
touch .env
```

Inhalt der `.env` — füge deine eigenen Werte ein:

```env
# --- Telegram ---
TELEGRAM_API_ID=DEINE_API_ID_ALS_ZAHL
TELEGRAM_API_HASH=dein_api_hash_string

# Zielgruppe — diese ID NICHT ändern!
TARGET_GROUP=-1003925024746

# --- Azure AI Foundry ---
AZURE_AI_FOUNDRY_KEY=dein_key_aus_schritt_5
AZURE_AI_FOUNDRY_ENDPOINT=https://dein-resource.services.ai.azure.com/api/projects/dein-projekt/openai/v1
AZURE_AI_FOUNDRY_DEPLOYMENT=gpt-4o-mini

# --- Azure Storage ---
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=DEIN_ACCOUNT;AccountKey=DEIN_KEY==;EndpointSuffix=core.windows.net

# --- Optional ---
AUTO_CLOSE_MINUTES=5
```

> ⚠️ Die `.env` Datei ist in `.gitignore` eingetragen — sie wird **nie** ins Repository gepusht. Das ist korrekt so.

---

## 7. Erster Start & Session-Authentifizierung

### 7.1 Backend starten

```bash
python main-azure.py
```

**Beim ersten Start fragt Telethon nach der Telegram-Authentifizierung:**

```
Please enter your phone (or bot token): +43XXXXXXXXX
Please enter the code you received: 12345
```

1. Handynummer eingeben (mit Ländervorwahl, z.B. `+43660...`)
2. Den Code eingeben, den Telegram per App/SMS schickt
3. Ggf. das Passwort (falls 2FA aktiviert)

Nach erfolgreicher Anmeldung wird eine Datei **`fareradar.session`** erstellt — diese speichert die Session lokal. Beim nächsten Start wird **nicht** mehr nach dem Code gefragt.

**Erfolgreiche Ausgabe sieht so aus:**

```
Starte SchwarzkapplerRadar (Azure AI Foundry Modus)...
  Modell: gpt-4o-mini
  Endpoint: https://...
  Azure Table Storage verbunden (Tabelle: kontrollen)
Verbunden! Lausche auf Nachrichten...
  [Auto-Close] Aktiv — schliesst Ereignisse nach 5 Min.
```

### 7.2 Test: Nachricht in die Testgruppe schicken

Schreibe eine Testnachricht in die Telegram-Gruppe, z.B.:

```
Schwarzkappler bei Stephansplatz U1 Richtung Reumannplatz
```

Das Backend sollte ausgeben:

```
[2025-05-23 14:32:11] Neue Meldung von @deinname:
Text: Schwarzkappler bei Stephansplatz U1 Richtung Reumannplatz
KI-Analyse:
{
  "ereignis_typ": "Beginn",
  "linie": "U1",
  "ort": "Stephansplatz",
  "zusammenfassung": "Ticketkontrolle am Stephansplatz auf der U1",
  "konfidenz": 0.92,
  ...
}
→ Ereignis gespeichert (Typ: Beginn)
```

---

## 8. Frontend starten (Streamlit)

In einem **zweiten Terminal** (Backend muss weiter laufen):

```bash
streamlit run app.py
```

Der Browser öffnet sich automatisch auf **http://localhost:8501**

Das Dashboard zeigt:
- 🗺️ Interaktive Karte Wien mit allen aktiven Kontrollen
- 📋 Tabelle aller Ereignisse aus Azure Table Storage
- 🔄 Auto-Refresh alle 60 Sekunden

---

## 9. Architekturübersicht

```
Telegram Gruppe (-1003925024746)
         │
         │  Neue Nachricht
         ▼
  main-azure.py  (Telethon Client)
         │
         │  Text → KI-Analyse
         ▼
  Azure AI Foundry  (GPT-4o-mini)
         │
         │  Strukturiertes JSON zurück
         ▼
  Azure Table Storage  (Tabelle: "kontrollen")
         │
         │  Daten lesen
         ▼
     app.py  (Streamlit Dashboard)
         │
         ▼
  http://localhost:8501
```

---

## 10. Troubleshooting

### ❌ `ModuleNotFoundError`
```bash
pip install -r requirements.txt
```
Sicherstellen, dass die virtuelle Umgebung aktiviert ist.

---

### ❌ `KeyError: TELEGRAM_API_ID` oder ähnliches
Die `.env` Datei fehlt oder ist nicht im richtigen Ordner.  
Prüfen: `ls -la` (macOS/Linux) bzw. `dir /a` (Windows) — die `.env` muss im selben Ordner wie `main-azure.py` liegen.

---

### ❌ Telegram-Fehler `AuthKeyUnregisteredError`
Die Session-Datei ist abgelaufen. Lösung:
```bash
del fareradar.session   # Windows
rm fareradar.session    # macOS/Linux
python main-azure.py    # neu einloggen
```

---

### ❌ Azure `ResourceNotFoundError` (Tabelle nicht gefunden)
Die Tabelle `kontrollen` wurde in Azure noch nicht erstellt → Schritt 4.3 wiederholen.

---

### ❌ `openai.AuthenticationError`
`AZURE_AI_FOUNDRY_KEY` oder `AZURE_AI_FOUNDRY_ENDPOINT` in der `.env` falsch.  
Endpoint muss das Format haben: `https://NAME.services.ai.azure.com/api/projects/PROJEKT/openai/v1`

---

### ❌ Keine Nachrichten kommen an
- Prüfen ob du Mitglied der Gruppe bist
- `TARGET_GROUP` muss exakt `-1003925024746` sein (mit Minuszeichen!)
- Telegram-Account muss die Nachrichten der Gruppe sehen können

---

*Erstellt für Gruppe 1 — System Integration SS25*
