import os
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
from telethon import TelegramClient, events
import ollama

# --- 1. Umgebungsvariablen laden ---
env_path = find_dotenv()
load_dotenv(env_path)

API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
TARGET_GROUP = int(os.getenv('TARGET_GROUP'))

# --- 2. Telethon Client initialisieren ---
client = TelegramClient('fareradar', API_ID, API_HASH)

# --- 3. KI System-Prompt (Basierend auf FareRadar Spezifikation) ---
SYSTEM_PROMPT = """
Du bist die KI für 'FareRadar', ein System zur Erkennung von Ticketkontrollen in Wien.
Analysiere die folgende Telegram-Nachricht und extrahiere die relevanten Daten.

Regeln:
1. Antworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt. Kein anderer Text!
2. Der 'status' MUSS einer dieser Werte sein: "aktiv", "beendet", "frei", "unklar". (Standard bei neuen Sichtungen ist "aktiv").
3. Setze 'confidence' zwischen 0.0 (sehr unsicher) und 1.0 (absolut sicher).
4. Wenn eine Information nicht im Text steht, setze den Wert auf null.

Erwartetes JSON-Schema:
{
    "station": "Name der Station (z.B. Stephansplatz)",
    "linie": "Liniennummer (z.B. U1, 13A) oder null",
    "richtung": "Fahrtrichtung falls erwähnt, sonst null",
    "status": "aktiv | beendet | frei | unklar",
    "confidence": 0.95
}
"""

def verarbeite_telegram_nachricht(telegram_text, telegram_timestamp):
    """Schickt den Text an Llama 3.1 und ergänzt ID/Zeitstempel"""
    
    # 1. KI macht die Extraktion (Text -> JSON)
    response = ollama.chat(
        model='llama3.1', 
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': telegram_text}
        ],
        format='json' # <-- Zwingt das LLM, NUR JSON auszugeben!
    )
    
    # 2. JSON-String der KI in Python-Dictionary umwandeln
    llm_daten = json.loads(response['message']['content'])
    
    # 3. Python generiert die eindeutige ID und formatiert die Zeit
    station = llm_daten.get('station') or 'unbekannt'
    station_clean = station.replace(" ", "")
    linie = llm_daten.get('linie') or 'unbekannt'
    
    llm_daten['event_id'] = f"{station_clean}-{linie}-{telegram_timestamp.strftime('%Y%m%d%H%M')}"
    llm_daten['gemeldet_um'] = telegram_timestamp.isoformat()
    
    return llm_daten

# --- 4. Event-Listener für neue Nachrichten ---
@client.on(events.NewMessage(chats=TARGET_GROUP))
async def new_message_handler(event):
    text = event.message.message
    timestamp = event.message.date
    
    if not text:
        return
        
    print(f"\n[{timestamp}] NEUE MELDUNG: {text}")
    print("-> Verarbeite lokal mit Llama 3.1 (Bitte kurz warten)...")
    
    try:
        # Nachricht durch das lokale LLM verarbeiten lassen
        fertiges_json = verarbeite_telegram_nachricht(text, timestamp)
        
        print("-> ERFOLGREICH EXTRAHIERT:")
        # Gibt das fertige Dictionary als schön formatiertes JSON in der Konsole aus
        print(json.dumps(fertiges_json, indent=4, ensure_ascii=False))
        print("-" * 50)
        
        # (In Phase 3 kommt hier der Code hin, um das fertige JSON in die SQLite-DB zu schreiben)
        
    except Exception as e:
        print(f"Fehler bei der KI-Verarbeitung: {e}")

async def main():
    print("\nStarte SchwarzkapplerRadar (Lokal + Llama 3.1 Modus)...")
    await client.start()
    print("Erfolgreich verbunden! Warte auf Nachrichten aus der Testgruppe...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())