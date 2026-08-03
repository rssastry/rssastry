import requests
import os
from dotenv import load_dotenv

load_dotenv()

token   = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

print(f"Token  : {token[:20]}..." if token else "Token  : NOT FOUND in .env")
print(f"Chat ID: {chat_id}" if chat_id else "Chat ID: NOT FOUND in .env")

if not token:
    print("\nFix: Add TELEGRAM_BOT_TOKEN to your .env file")
else:
    url = "https://api.telegram.org/bot" + token + "/getUpdates"
    r   = requests.get(url)
    data = r.json()

    if data.get("ok"):
        messages = data.get("result", [])
        if not messages:
            print("\nNo messages found.")
            print("Go to Telegram, find your bot, send it 'hello', then run this again.")
        else:
            for msg in messages:
                chat = msg.get("message", {}).get("chat", {})
                print(f"\nFound Chat ID : {chat.get('id')}")
                print(f"From          : {chat.get('first_name','?')} {chat.get('last_name','')}")
                print("\nCopy that Chat ID into your .env file as TELEGRAM_CHAT_ID=xxxxxxxx")
    else:
        print("\nAPI Error:", data)
        print("Your bot token is likely wrong. Get a fresh one from @BotFather on Telegram.")