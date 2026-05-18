import os
import asyncio
from dotenv import load_dotenv, find_dotenv
from telethon import TelegramClient, events

# Sucht aktiv nach der .env Datei und lädt sie
env_path = find_dotenv()
print(f"-> Suche .env Datei... Gefunden hier: '{env_path}'")
load_dotenv(env_path)

# Sicheres Auslesen mit Fehlerabfrage
api_id_str = os.getenv('TELEGRAM_API_ID')

if not api_id_str:
    print("FEHLER: Konnte TELEGRAM_API_ID nicht finden. Liegt die .env Datei wirklich im selben Ordner?")
    exit()

API_ID = int(api_id_str)
API_HASH = os.getenv('TELEGRAM_API_HASH')

# Client initialisieren
client = TelegramClient('fareradar', API_ID, API_HASH)

@client.on(events.NewMessage)
async def id_finder_handler(event):
    text = event.message.message
    chat_id = event.chat_id
    
    if not text:
        return
        
    print(f"\n--- NEUE NACHRICHT EMPFANGEN ---")
    print(f"Chat ID: {chat_id}")
    print(f"Text: {text}")
    print("-" * 32)
    print("-> Wenn das die Testgruppe war: Kopiere dir diese Chat ID!")

async def main():
    print("\nStarte FareRadar ID-Finder...")
    await client.start()
    print("Erfolgreich verbunden!")
    print("Bitte schreibe jetzt genau EINE Test-Nachricht in deine neue Telegram-Gruppe 'SchwarzkapplerRadar Test'...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())