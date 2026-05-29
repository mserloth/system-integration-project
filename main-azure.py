import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv, find_dotenv
from telethon import TelegramClient, events
from openai import OpenAI
from azure.data.tables import TableServiceClient, UpdateMode
from rapidfuzz import process, fuzz

load_dotenv(find_dotenv())

TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID'))
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')
TARGET_GROUP = int(os.getenv('TARGET_GROUP'))

AZURE_KEY = os.getenv('AZURE_AI_FOUNDRY_KEY')
AZURE_ENDPOINT = os.getenv('AZURE_AI_FOUNDRY_ENDPOINT')
AZURE_DEPLOYMENT = os.getenv('AZURE_AI_FOUNDRY_DEPLOYMENT', 'gpt-5-mini')
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING')

#If the variable isn't in .env at all, it stays at X minutes.
AUTO_CLOSE_MINUTES = int(os.getenv("AUTO_CLOSE_MINUTES", 5))
CHECK_INTERVAL_SECONDS = 60

ai_client = OpenAI(
    api_key=AZURE_KEY,
    base_url=AZURE_ENDPOINT,
)

telegram_client = TelegramClient('fareradar', TELEGRAM_API_ID, TELEGRAM_API_HASH)

table_service = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
table_client = table_service.get_table_client("kontrollen")


def init_storage():
    """Initialisiert die Azure Table Storage Tabelle beim Programmstart.

    Stellt sicher, dass die Tabelle 'kontrollen' in Azure Table Storage existiert.
    Wird beim Start von main() aufgerufen. Ist die Tabelle bereits vorhanden,
    hat der Aufruf keinen Effekt (idempotent).
    """
    table_service.create_table_if_not_exists("kontrollen")
    print("  Azure Table Storage verbunden (Tabelle: kontrollen)")


def analyse_mit_ki(text: str, timestamp: str) -> dict:
    """Analysiert einen Telegram-Nachrichtentext mit Azure AI Foundry (GPT) und gibt ein strukturiertes Ereignis zurück.

    Sendet den Nachrichtentext an das konfigurierte Azure-Sprachmodell mit einem
    festen System-Prompt, der das Modell zu einer reinen JSON-Antwort zwingt.
    Bereinigt optional vorhandene Markdown-Codeblöcke aus der Antwort und ergänzt
    das Ergebnis um Zeitstempel-Felder. Läuft synchron und wird via
    asyncio.to_thread() aus dem async Kontext aufgerufen.

    Args:
        text (str): Rohtext der Telegram-Nachricht, der analysiert werden soll.
        timestamp (str): ISO-Zeitstempel der Nachricht, wird dem Ergebnis als
                         'gestartet_am' hinzugefügt.

    Returns:
        dict: Strukturiertes Ereignis-Objekt mit den Feldern:
              - ereignis_typ (str): "Beginn" oder "Ende"
              - linie (str | None): Liniennummer, z.B. "U3"
              - ort (str | None): Haltestellenname
              - zusammenfassung (str): Kurze Beschreibung des Ereignisses
              - konfidenz (float): Modell-Konfidenz zwischen 0.0 und 1.0
              - gestartet_am (str): Zeitstempel der Nachricht
              - beendet_am (str): Leerstring (wird ggf. später gesetzt)

    Raises:
        ValueError: Wenn das Modell eine leere Antwort zurückgibt.
        json.JSONDecodeError: Wenn die Modell-Antwort kein gültiges JSON enthält.
    """
    response = ai_client.chat.completions.create(
        model=AZURE_DEPLOYMENT,
        messages=[
            {
                "role": "developer",
                "content": (
                    "Du bist ein Assistent, der Telegram-Nachrichten analysiert. "
                    "Antworte NUR mit einem reinen JSON-Objekt, ohne Markdown, ohne Codeblock, ohne Erklärung. "
                    "Felder: "
                    "\"ereignis_typ\" (Beginn/Ende — ist das der Start einer Kontrolle oder das Ende?), "
                    "\"linie\" (Liniennummer als String oder null), "
                    "\"ort\" (Haltestellenname oder null), "
                    "\"zusammenfassung\" (ein kurzer Satz), "
                    "\"konfidenz\" (Zahl zwischen 0.0 und 1.0 — wie sicher du dir bei der Analyse bist)."
                ),
            },
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=2000,
    )
    raw = response.choices[0].message.content
    if not raw:
        raise ValueError(f"Leere Antwort vom Modell (finish_reason={response.choices[0].finish_reason})")
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    result["gestartet_am"] = timestamp
    result["beendet_am"] = ""
    return result


def _row_key(timestamp: str) -> str:
    """Wandelt einen ISO-Zeitstempel in einen gültigen Azure Table Storage RowKey um.

    Azure Table Storage erlaubt in RowKeys keine Sonderzeichen wie ':', '+', ' '
    oder '/'. Diese Funktion ersetzt alle unzulässigen Zeichen durch sichere
    Alternativen, sodass der Zeitstempel als eindeutiger RowKey verwendet werden kann.

    Args:
        timestamp (str): ISO-Zeitstempel, z.B. "2024-05-20 14:32:00+00:00".

    Returns:
        str: Bereinigter RowKey, z.B. "2024-05-20_14-32-00p00-00".
    """
    return (timestamp
            .replace(":", "-")
            .replace("+", "p")
            .replace(" ", "_")
            .replace("/", "-"))


def speichere_ereignis(analyse: dict):
    """Speichert oder aktualisiert ein KI-analysiertes Ereignis in Azure Table Storage.

    Implementiert die vollständige Speicher-Logik mit drei Fällen:
    1. Konfidenz < 0.2 → Ereignis wird verworfen (zu unsicher).
    2. ereignis_typ == "Beginn" → Duplikat-Check (gleiche Linie + Ort noch offen?).
       Ist kein Duplikat vorhanden, wird ein neuer Eintrag erstellt.
    3. ereignis_typ == "Ende" → Versucht ein passendes offenes Ereignis zu schließen:
       - Pass 1: Exakter Match auf Linie + Ort.
       - Pass 2: Fuzzy-Match auf Ort über alle offenen Ereignisse (≥ 70 % WRatio).
       Wird kein Match gefunden, wird das "Ende" direkt als geschlossen gespeichert,
       damit es nie als aktiv erscheint.

    Args:
        analyse (dict): Ergebnis-Dict aus analyse_mit_ki() mit den Feldern
                        ereignis_typ, linie, ort, zusammenfassung, konfidenz,
                        gestartet_am, beendet_am.
    """
    konfidenz = float(analyse.get("konfidenz", 0.0))
    if konfidenz < 0.2:
        print(f"  → Zu niedrige Konfidenz ({konfidenz:.2f}), Ereignis wird nicht gespeichert.")
        return

    kategorie = "Kontrolle"
    linie = str(analyse.get("linie") or "")
    ort = str(analyse.get("ort") or "")
    ereignis_typ = analyse.get("ereignis_typ", "Beginn")

    if ereignis_typ == "Beginn" and (linie or ort):
        if linie and ort:
            dup_filter = f"PartitionKey eq '{kategorie}' and linie eq '{linie}' and ort eq '{ort}' and beendet_am eq ''"
        elif ort:
            dup_filter = f"PartitionKey eq '{kategorie}' and ort eq '{ort}' and beendet_am eq ''"
        else:
            dup_filter = f"PartitionKey eq '{kategorie}' and linie eq '{linie}' and beendet_am eq ''"
        existing = list(table_client.query_entities(dup_filter))
        if existing:
            print(f"  → Duplikat erkannt, bereits offen seit {existing[0].get('gestartet_am')} — wird ignoriert.")
            return

    if ereignis_typ == "Ende":
        # Pass 1: exact match on line + station
        entities = []
        if linie and ort:
            entities = list(table_client.query_entities(
                f"PartitionKey eq '{kategorie}' and linie eq '{linie}' and ort eq '{ort}' and beendet_am eq ''"
            ))
        # Pass 2: fuzzy station match across all open events
        if not entities and ort:
            open_events = list(table_client.query_entities(
                f"PartitionKey eq '{kategorie}' and beendet_am eq ''"
            ))
            if open_events:
                ort_list = [e.get("ort", "") for e in open_events]
                result = process.extractOne(ort, ort_list, scorer=fuzz.WRatio)
                if result is not None and result[1] >= 70:
                    print(f"  → Fuzzy-Match: '{ort}' → '{result[0]}' (Score: {result[1]})")
                    entities = [open_events[result[2]]]
        if entities:
            entity = sorted(entities, key=lambda x: x.get("gestartet_am", ""))[-1]
            entity["beendet_am"] = analyse["gestartet_am"]
            table_client.update_entity(entity, mode=UpdateMode.MERGE)
            print(f"  → Offenes Ereignis geschlossen (gestartet: {entity.get('gestartet_am')})")
            return

    # An unmatched "Ende" goes directly to closed so it never appears as active
    beendet_am = analyse["gestartet_am"] if ereignis_typ == "Ende" else ""

    entity = {
        "PartitionKey": kategorie,
        "RowKey": _row_key(analyse["gestartet_am"]),
        "ereignis_typ": ereignis_typ,
        "linie": linie,
        "ort": ort,
        "zusammenfassung": str(analyse.get("zusammenfassung", "")),
        "konfidenz": float(analyse.get("konfidenz", 0.0)),
        "gestartet_am": analyse["gestartet_am"],
        "beendet_am": beendet_am,
    }
    table_client.create_entity(entity)
    print(f"  → Ereignis gespeichert (Typ: {ereignis_typ})")


async def auto_close_stale_events():
    """Hintergrund-Task, der veraltete offene Ereignisse automatisch schließt.

    Läuft als endlose asyncio-Schleife und prüft alle CHECK_INTERVAL_SECONDS (60 s),
    ob noch offene Ereignisse (beendet_am == '') existieren, deren Startzeit älter
    als AUTO_CLOSE_MINUTES ist. Solche Ereignisse werden mit dem aktuellen UTC-Zeitstempel
    als beendet_am markiert und per MERGE-Update in Azure Table Storage aktualisiert.

    Die Funktion verhindert, dass Ereignisse dauerhaft als aktiv erscheinen, wenn
    kein explizites "Ende"-Signal in Telegram gesendet wurde.

    Note:
        AUTO_CLOSE_MINUTES und CHECK_INTERVAL_SECONDS werden aus den Umgebungs-
        variablen geladen (Standard: 5 Min. / 60 s). Fehler im Loop werden
        abgefangen und geloggt, ohne den Task zu beenden.
    """
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=AUTO_CLOSE_MINUTES)
            entities = list(table_client.query_entities("beendet_am eq ''"))
            closed = 0
            for entity in entities:
                gestartet = entity.get("gestartet_am", "")
                if not gestartet:
                    continue
                try:
                    started_at = datetime.fromisoformat(str(gestartet))
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if started_at < cutoff:
                    entity["beendet_am"] = datetime.now(timezone.utc).isoformat()
                    table_client.update_entity(entity, mode=UpdateMode.MERGE)
                    closed += 1
                    print(f"  → Auto-geschlossen: {entity.get('ort', '?')} (gestartet: {gestartet})")
            if closed:
                print(f"  [Auto-Close] {closed} Ereignis(se) nach {AUTO_CLOSE_MINUTES} Min. geschlossen.")
        except Exception as e:
            print(f"  [Auto-Close] Fehler: {e}")


@telegram_client.on(events.NewMessage(chats=TARGET_GROUP))
async def new_message_handler(event):
    """Telethon-Event-Handler für neue Nachrichten in der überwachten Telegram-Gruppe.

    Wird von Telethon automatisch aufgerufen, sobald eine neue Nachricht in
    TARGET_GROUP eintrifft. Extrahiert Text, Zeitstempel und Absender, übergibt
    den Text an analyse_mit_ki() (via asyncio.to_thread, da synchron) und
    speichert das Ergebnis via speichere_ereignis(). Leere Nachrichten (z.B.
    reine Medien-Posts) werden stillschweigend ignoriert.

    Args:
        event: Telethon NewMessage-Event mit den Attributen message.message
               (Text), message.date (Zeitstempel) und get_sender() (Absender).
    """
    text = event.message.message
    timestamp = event.message.date
    sender = await event.get_sender()
    sender_name = sender.username if sender and sender.username else "Unbekannt"

    if not text:
        return

    print(f"\n[{timestamp}] Neue Meldung von @{sender_name}:")
    print(f"Text: {text}")

    try:
        antwort = await asyncio.to_thread(analyse_mit_ki, text, str(timestamp))
        print("KI-Analyse:")
        print(json.dumps(antwort, indent=2, ensure_ascii=False))
        await asyncio.to_thread(speichere_ereignis, antwort)
    except Exception as e:
        print(f"KI-Fehler: {e}")
    print("-" * 50)


async def main():
    """Einstiegspunkt der Anwendung — initialisiert alle Dienste und startet die Event-Loop.

    Führt beim Start folgende Schritte aus:
    1. Gibt Konfigurationsinfo (Modell, Endpoint) aus.
    2. Initialisiert Azure Table Storage via init_storage().
    3. Startet den Telegram-Client und verbindet sich mit der API.
    4. Startet auto_close_stale_events() als Hintergrund-Task.
    5. Blockiert in telegram_client.run_until_disconnected() bis das Programm
       manuell beendet oder die Verbindung getrennt wird.
    """
    print("\nStarte SchwarzkapplerRadar (Azure AI Foundry Modus)...")
    print(f"  Modell: {AZURE_DEPLOYMENT}")
    print(f"  Endpoint: {AZURE_ENDPOINT}")
    init_storage()
    await telegram_client.start()
    print("Verbunden! Lausche auf Nachrichten...\n")
    print(f"  [Auto-Close] Aktiv — schliesst Ereignisse nach {AUTO_CLOSE_MINUTES} Min.")  # NEW
    asyncio.get_event_loop().create_task(auto_close_stale_events())  # NEW
    await telegram_client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
