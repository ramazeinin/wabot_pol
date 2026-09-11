import os
import json
import requests
from datetime import datetime
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

# Read variables from environment
WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "http://waha:3000")
WAHA_SESSION = "default"
WAHA_API_KEY = os.getenv("WAHA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SHEET_WEBHOOK_URL = os.getenv("SHEET_WEBHOOK_URL")

HEADERS = {
    "X-Api-Key": WAHA_API_KEY,
    "Content-Type": "application/json"
}

app = FastAPI()
import httpx
from groq import Groq

# Replace groq_client = Groq(api_key=GROQ_API_KEY) with:
groq_client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client())

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

    if event_type == "message":
        raw_body = data.get("body")
        body = str(raw_body).strip() if raw_body else ""
        chat_id = data.get("from")

        if not body or body == "None":
            return {"status": "ignored_no_text"}

        parsed = parse_expense_with_groq(body)
        amount = parsed.get("amount", 0)

        if amount <= 0:
            send_whatsapp_text(chat_id, "Maaf, nominal transaksi tidak ditemukan.")
            return {"status": "no_amount"}

        # Send data to Apps Script Web App
        requests.post(SHEET_WEBHOOK_URL, json={
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": parsed.get("description"),
            "category": parsed.get("category"),
            "type": parsed.get("type"),
            "amount": amount
        })

        reply_msg = f"✅ Tercatat!\n• {parsed.get('description')}\n• Rp {amount:,} ({parsed.get('category')})"
        send_whatsapp_text(chat_id, reply_msg)
        return {"status": "saved"}

    return {"status": "ok"}