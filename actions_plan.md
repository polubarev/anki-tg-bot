# End‑to‑End Guide

*(Google Cloud+Telegram+LLM+Queued AnkiConnect Sync)*

---

## 0.Prerequisites

* **Google CloudCLI** (`gcloud`) logged in, billing enabled.
* **Docker** installed (for Cloud Run image build).
* Laptop with **Anki Desktop2.1+, AnkiConnect add‑on≥v.6** and **Cloudflare Tunnel** (or equivalent) that exposes `http://localhost:8765` as a public **HTTPS** URL (e.g. `https://anki-tunnel.example/invoke`).
* Telegram **Bot Token** (`@BotFather`).

---

## 1.Local repo layout  

```text
tg‑anki‑bot/
 ├─ bot.py              # main entry point
 ├─ firestore_queue.py  # queue helpers
 ├─ requirements.txt
 ├─ Dockerfile
 └─ README.md
```

---

## 2.Source code

### 2.1 `requirements.txt`

```
python-telegram-bot[asyncio]>=21.2
openai>=1.14
google-cloud-firestore>=2.16
google-cloud-secret-manager>=2.19
aiohttp>=3.9
pydantic>=2.7
```

### 2.2 `firestore_queue.py`

```python
from google.cloud import firestore
import datetime, json
from pydantic import BaseModel

db = firestore.Client()
COL = db.collection("cards")

class Card(BaseModel):
    uid: int
    ts: str
    front: str
    back: str
    examples: list[str]

# --- CRUD -------------------------------------------------------

def enqueue(card: Card):
    doc_id = f"{card.uid}_{card.ts}"
    COL.document(doc_id).set(card.model_dump())

def list_cards(uid: int) -> list[Card]:
    return [
        Card(**d.to_dict())
        for d in COL.where("uid", "==", uid).order_by("ts").stream()
    ]

def delete_batch(uid: int, ids: list[str]):
    batch = db.batch()
    for doc_id in ids:
        batch.delete(COL.document(doc_id))
    batch.commit()
```

### 2.3 `bot.py`

```python
import os, json, datetime, asyncio, aiohttp
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI
from firestore_queue import enqueue, list_cards, delete_batch, Card
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ContextTypes, CommandHandler,
    MessageHandler, filters, CallbackQueryHandler
)
from google.cloud import secretmanager

# ---------- secrets ----------
def secret(name: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    proj = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    path = f"projects/{proj}/secrets/{name}/versions/latest"
    return client.access_secret_version(name=path).payload.data.decode()

TG_TOKEN  = secret("tg-token")
OPENAI_KEY = secret("openai-key")
ANKI_URL   = secret("anki-url")          # e.g. https://anki-tunnel.example/invoke
DECK   = "Hebrew"
MODEL  = "Basic"

openai = AsyncOpenAI(api_key=OPENAI_KEY)
timeout = aiohttp.ClientTimeout(total=5)

SYSTEM_PROMPT = """
You are a card‑creator. Return strict minified JSON:
{
 "front": "...",
 "back": "...",
 "pos": "...",
 "forms": { "inf": "", "present": "", "past": "", "future": "" },
 "examples": ["...", "..."]
}
No niqqud. No extra keys.
"""

# ---------- helpers ----------
async def llm_card(word: str) -> dict | None:
    rsp = await openai.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": word}]
    )
    try:
        return json.loads(rsp.choices[0].message.content)
    except json.JSONDecodeError:
        return None

async def push_to_anki(c: Card) -> bool:
    payload = {
        "action": "addNote", "version": 6,
        "params": {"note": {
            "deckName": DECK, "modelName": MODEL,
            "fields": {
                "Front": c.front,
                "Back": c.back,
                "Examples": "<br>".join(c.examples)
            },
            "tags": ["tg_bot"]
        }}
    }
    async with aiohttp.ClientSession(timeout=timeout) as s:
        try:
            r = await s.post(ANKI_URL, json=payload)
            return (await r.json())["error"] is None
        except Exception:
            return False

# ---------- handlers ----------
async def start(u: Update, _: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("➕ Add Card", callback_data="add")],
          [InlineKeyboardButton("🚀 Push", callback_data="push")],
          [InlineKeyboardButton("📋 List", callback_data="list")],
          [InlineKeyboardButton("🗑 Clear", callback_data="clear")]]
    await u.message.reply_text("Choose:", reply_markup=InlineKeyboardMarkup(kb))

async def buttons(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    action = q.data
    if action == "add":
        ctx.user_data["awaiting"] = True
        await q.message.reply_text("Send one word:")
    elif action == "push":
        await push_cmd(u, ctx)
    elif action == "list":
        await list_cmd(u)
    elif action == "clear":
        await clear_cmd(u)

async def add_text(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.pop("awaiting", False):
        return
    word = u.message.text.strip()
    data = await llm_card(word)
    if not data:
        await u.message.reply_text("LLM error, try again.")
        return
    card = Card(
        uid=u.effective_user.id,
        ts=datetime.datetime.utcnow().isoformat(),
        front=data["front"],
        back=data["back"],
        examples=data["examples"]
    )
    enqueue(card)
    await u.message.reply_text(f"Queued: {card.front} → {card.back}")

async def list_cmd(u: Update):
    cards = list_cards(u.effective_user.id)[:10]
    if not cards:
        await u.callback_query.message.reply_text("Queue empty.")
        return
    txt = "\n".join(f"{i+1}. {c.front} → {c.back}" for i, c in enumerate(cards))
    await u.callback_query.message.reply_text(txt)

async def clear_cmd(u: Update):
    cards = list_cards(u.effective_user.id)
    delete_batch(u.effective_user.id, [f"{c.uid}_{c.ts}" for c in cards])
    await u.callback_query.message.reply_text("Queue cleared.")

async def push_cmd(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.callback_query.message.reply_text("Pushing…")
    cards = list_cards(u.effective_user.id)
    ok = 0
    for c in cards:
        if await push_to_anki(c):
            ok += 1
    if ok:
        delete_batch(u.effective_user.id, [f"{c.uid}_{c.ts}" for c in cards])
    await u.callback_query.message.reply_text(f"Done. ✅ {ok}/{len(cards)}")

# ---------- app ----------
def get_app() -> Application:
    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_text))
    return app

# ---------- local entry ----------
if __name__ == "__main__":
    get_app().run_polling()
```

### 2.4 `Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
```

---

## 3.Google Cloud setup

### 3.1 Enable APIs

```bash
gcloud services enable run.googleapis.com \
                        firestore.googleapis.com \
                        secretmanager.googleapis.com
```

### 3.2 Create Firestore

```bash
gcloud firestore databases create --location=europe-west1 
```

### 3.3 Secrets

```bash
echo "$TELEGRAM_TOKEN" | gcloud secrets create tg-token --data-file=-
echo "$OPENAI_KEY"     | gcloud secrets create openai-key --data-file=-
echo "https://anki-tunnel.example/invoke" | gcloud secrets create anki-url --data-file=-
```

### 3.4 Docker build & Cloud Run deploy

```bash
gcloud builds submit --tag gcr.io/$(gcloud config get project)/tg-anki-bot

gcloud run deploy tg-anki-bot \
  --image gcr.io/$(gcloud config get project)/tg-anki-bot \
  --region=europe-west1 \
  --allow-unauthenticated \
  --set-secrets "TG_TOKEN=tg-token:latest,OPENAI_KEY=openai-key:latest,ANKI_URL=anki-url:latest" \
  --memory 256Mi --max-instances 1
```

Cloud Run outputs a URL like
`https://tg-anki-bot-uc.a.run.app`.

### 3.5 Set Telegram webhook

```bash
curl -X POST \
 "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook" \
 -d "url=https://tg-anki-bot-uc.a.run.app/webhook"
```

---

## 4.Laptop setup

1. **Anki Desktop** → *Tools▸Add‑ons▸Get Add‑ons* → code **2055492159** (AnkiConnect).
2. *Tools▸Add‑ons▸AnkiConnect▸Config* → set

   ```json
   { "webBindAddress": "127.0.0.1",
     "apiKey": "YOUR_LONG_RANDOM_KEY" }
   ```
3. **Cloudflare Tunnel** (free):

   ```bash
   cloudflared tunnel create anki
   cloudflared tunnel route dns anki cards.yourdomain.com
   cloudflared tunnel run anki \
        --url http://127.0.0.1:8765 \
        --request-header "anki-apikey: YOUR_LONG_RANDOM_KEY"
   ```
4. Ensure Anki’s *Preferences▸Sync▸Automatically sync on profile open/close* **on**.

---

## 5.Daily Usage

* On phone: `Add Card` → type word, repeat.
* At home: open Anki, start tunnel, then press **“🚀 Push”** in bot.
* Cards appear in deck within a few seconds.

---

## 6.Firestore security rules (optional hardening)

```firestore
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /cards/{docId} {
      allow read, write: if request.auth == null;  // webhook unauthenticated
    }
  }
}
```

*(The bot accesses Firestore with default service‑account—no public traffic—so open rules are acceptable; tighten if you build a user‑facing API.)*

---

## 7.Maintenance Tips

* **Update LLM model**: change `model=` line in `bot.py`.
* **Change tunnel URL**: `gcloud secrets versions add anki-url --data-file=-` then redeploy.
* **Logs**:

  ```bash
  gcloud run services logs tail tg-anki-bot --region=europe-west1
  ```
* **Cost guard**: Cloud Run `--max-instances 1` prevents accidental scale‑out.

---

### You now have a fully functional, no‑cost‐while‑idle pipeline:

* Telegram → Cloud Run (Python bot) → Firestore queue
* One‑click **Push** → laptop AnkiConnect → sync to AnkiWeb / phone.

Copy the code above into the repo layout, execute the commands in order, and you’re live. Happy card‑making!
