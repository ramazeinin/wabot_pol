import os
import json
import requests
from datetime import datetime
from fastapi import FastAPI, Request
from groq import Groq
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "http://localhost:3000")
WAHA_SESSION = "default"
WAHA_API_KEY = os.getenv("WAHA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SHEET_WEBHOOK_URL = os.getenv("SHEET_WEBHOOK_URL")

HEADERS = {
    "X-Api-Key": WAHA_API_KEY,
    "Content-Type": "application/json"
}

app = FastAPI()
groq_client = Groq(api_key=GROQ_API_KEY)

# Google Sheets Setup
# scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
# creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
# gc = gspread.authorize(creds)
# sheet = gc.open(SPREADSHEET_NAME).sheet1


def send_whatsapp_text(chat_id: str, text: str):
    requests.post(
        f"{WAHA_BASE_URL}/api/sendText",
        headers=HEADERS,
        json={"session": WAHA_SESSION, "chatId": chat_id, "text": text}
    )


def parse_expense_with_groq(user_story: str) -> dict:
    prompt = f"""
    Kamu adalah asisten pencatat keuangan pribadi.
    Ekstrak data transaksi dari teks berbahasa Indonesia berikut:
    "{user_story}"

    Keluarkan HANYA JSON murni dengan format berikut:
    {{
      "amount": (integer tanpa titik/koma, contoh 50000),
      "category": (string kategori ringkas, contoh: "Makanan & Minuman", "Transportasi", "Belanja", "Tagihan", "Lainnya"),
      "type": ("Pengeluaran" atau "Pemasukan"),
      "description": (ringkasan belanja/item yang dibeli)
    }}
    Jika tidak ada nominal uang yang ditemukan, isi amount dengan 0.
    """

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


@app.post("/webhook")
async def handle_whatsapp_webhook(request: Request):
    payload = await request.json()
    event_type = payload.get("event")
    data = payload.get("payload", {})

    # Only process incoming messages
    if event_type == "message":
        raw_body = data.get("body")
        body = str(raw_body).strip() if raw_body else ""
        chat_id = data.get("from")

        if not body or body == "None":
            return {"status": "ignored_no_text"}

        # Extract transaction using LLM
        parsed = parse_expense_with_groq(body)
        amount = parsed.get("amount", 0)

        if amount <= 0:
            send_whatsapp_text(
                chat_id,
                "Maaf, saya tidak menemukan nominal transaksi yang jelas dari pesanmu."
            )
            return {"status": "no_amount"}

        # Save directly to Google Sheet
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        requests.post(SHEET_WEBHOOK_URL, json={
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": parsed.get("description"),
            "category": parsed.get("category"),
            "type": parsed.get("type"),
            "amount": parsed.get("amount")
        })

        # Reply with a short summary confirming it was saved
        reply_msg = (
            f"✅ Tercatat!\n"
            f"• {parsed.get('description')}\n"
            f"• Rp {amount:,} ({parsed.get('category')})"
        )
        send_whatsapp_text(chat_id, reply_msg)
        return {"status": "saved_directly"}

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)