import os
import asyncio
from dotenv import load_dotenv, find_dotenv
from telethon import TelegramClient, events

# 1. Umgebungsvariablen laden
env_path = find_dotenv()
load_dotenv(env_path)

API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
TARGET_GROUP = int(os.getenv('TARGET_GROUP')) # ID der Testgruppe (muss ein int sein!)

# 2. Client initialisieren
client = TelegramClient('fareradar', API_ID, API_HASH)

# 3. Der Filter: Skript lauscht NUR noch auf die Testgruppe
@client.on(events.NewMessage(chats=TARGET_GROUP))
async def new_message_handler(event):
    text = event.message.message
    timestamp = event.message.date
    sender = await event.get_sender()
    sender_name = sender.username if sender and sender.username else "Unbekannt"
    
    if not text:
        return
        
    print(f"\n[{timestamp}] Meldung aus der Testgruppe (@{sender_name}):")
    print(f"Text: {text}")
    print("-" * 50)
    
    # ---> HIER kommt im nächsten Schritt die OpenAI API hin! <---

async def main():
    print("\nStarte SchwarzkapplerRadar (Testgruppen-Modus)...")
    await client.start()
    print("Erfolgreich verbunden! Das Skript ist jetzt sicherisiert und lauscht NUR auf die Testgruppe.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())