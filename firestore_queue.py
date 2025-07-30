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
    pos: str
    forms: dict[str, str]
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
