import os, json, datetime, asyncio, aiohttp
from firestore_queue import enqueue, list_cards, delete_batch, Card
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ContextTypes, CommandHandler,
    MessageHandler, filters, CallbackQueryHandler
)
from google.cloud import secretmanager
from llm_service import llm_card

# ---------- secrets ----------
def secret(name: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    proj = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    path = f"projects/{proj}/secrets/{name}/versions/latest"
    return client.access_secret_version(name=path).payload.data.decode()

TG_TOKEN  = secret("tg-token")
ANKI_URL   = secret("anki-url")          # e.g. https://anki-tunnel.example/invoke
DECK   = "Hebrew"
MODEL  = "Basic"

timeout = aiohttp.ClientTimeout(total=5)

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
        front=data.front,
        back=data.back,
        pos=data.pos,
        forms=data.forms,
        examples=data.examples
    )
    enqueue(card)
    await u.message.reply_text(f"Queued: {card.front} → {card.back}")

async def list_cmd(u: Update):
    cards = list_cards(u.effective_user.id)[:10]
    if not cards:
        await u.callback_query.message.reply_text("Queue empty.")
        return
    txt = "".join(f"{i+1}. {c.front} → {c.back}" for i, c in enumerate(cards))
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
