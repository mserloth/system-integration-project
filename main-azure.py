import os
import json
import asyncio
from datetime import datetime, timezone, timedelta  # NEW
from dotenv import load_dotenv, find_dotenv
from telethon import TelegramClient, events
from openai import OpenAI
from azure.data.tables import TableServiceClient, UpdateMode

load_dotenv(find_dotenv())

TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID'))
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')
TARGET_GROUP = int(os.getenv('TARGET_GROUP'))

AZURE_KEY = os.getenv('AZURE_AI_FOUNDRY_KEY')
AZURE_ENDPOINT = os.getenv('AZURE_AI_FOUNDRY_ENDPOINT')
AZURE_DEPLOYMENT = os.getenv('AZURE_AI_FOUNDRY_DEPLOYMENT', 'gpt-5-mini')
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING')

# NEW — change AUTO_CLOSE_MINUTES for the live demo (e.g. 1, 3, 5 — default: 90)
AUTO_CLOSE_MINUTES = 5
# NEW — how often the cleanup check runs (in seconds)
CHECK_INTERVAL_SECONDS = 60

ai_client = OpenAI(
    api_key=AZURE_KEY,
    base_url=AZURE_ENDPOINT,
)

telegram_client = TelegramClient('fareradar', TELEGRAM_API_ID, TELEGRAM_API_HASH)

table_service = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
table_client = table_service.get_table_client("kontrollen")


def init_storage():
    table_service.create_table_if_not_exists("kontrollen")
    print("  Azure Table Storage verbunden (Tabelle: kontrollen)")


def analyse_mit_ki(text: str, timestamp: str) -> dict:
    response = ai_client.chat.completions.create(
        model=AZURE_DEPLOYMENT,
        messages=[
            {
                "role": "developer",
                "content": (
                    "Du bist ein Assistent, der Telegram-Nachrichten analysiert. "
                    "Antworte NUR mit einem reinen JSON-Objekt, ohne Markdown, ohne Codeblock, ohne Erklärung. "
                    "Felder: "
                    "\"wichtig\" (true/false), "
                    "\"kategorie\" (Kontrolle/Unfall/Stau/Sonstiges), "
                    "\"ereignis_typ\" (Beginn/Ende/Einzelmeldung — ist das der Start einer Kontrolle, das Ende, oder eine einmalige Meldung?), "
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
    return (timestamp
            .replace(":", "-")
            .replace("+", "p")
            .replace(" ", "_")
            .replace("/", "-"))


def speichere_ereignis(analyse: dict):
    kategorie = analyse.get("kategorie", "Sonstiges")
    linie = str(analyse.get("linie") or "")
    ort = str(analyse.get("ort") or "")
    ereignis_typ = analyse.get("ereignis_typ", "Einzelmeldung")

    if ereignis_typ == "Ende":
        filter_str = (
            f"PartitionKey eq '{kategorie}' "
            f"and linie eq '{linie}' "
            f"and ort eq '{ort}' "
            f"and beendet_am eq ''"
        )
        entities = list(table_client.query_entities(filter_str))
        if entities:
            entity = sorted(entities, key=lambda x: x.get("gestartet_am", ""))[-1]
            entity["beendet_am"] = analyse["gestartet_am"]
            table_client.update_entity(entity, mode=UpdateMode.MERGE)
            print(f"  → Offenes Ereignis geschlossen (gestartet: {entity.get('gestartet_am')})")
            return

    entity = {
        "PartitionKey": kategorie,
        "RowKey": _row_key(analyse["gestartet_am"]),
        "wichtig": bool(analyse.get("wichtig", False)),
        "ereignis_typ": ereignis_typ,
        "linie": linie,
        "ort": ort,
        "zusammenfassung": str(analyse.get("zusammenfassung", "")),
        "konfidenz": float(analyse.get("konfidenz", 0.0)),
        "gestartet_am": analyse["gestartet_am"],
        "beendet_am": "",
    }
    table_client.create_entity(entity)
    print(f"  → Ereignis gespeichert (Typ: {ereignis_typ})")


# NEW — background loop that auto-closes events older than AUTO_CLOSE_MINUTES
async def auto_close_stale_events():
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
