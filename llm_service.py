import openai
from pydantic import BaseModel
import json
import os

class AnkiCard(BaseModel):
    front: str
    back: str
    pos: str
    forms: dict[str, str]
    examples: list[str]

async def llm_card(word: str) -> AnkiCard | None:
    """
    Creates an Anki card from the given text using OpenAI.
    """
    client = openai.AsyncOpenAI()
    prompt = f'''
Create anki cards from the text below.
Text: "{word}"
Provide response in JSON format, as a list of objects with keys "front", "back", "pos", "forms", and "examples".
Example:
{{
    "front": "front side of the card",
    "back": "back side of the card",
    "pos": "part of speech",
    "forms": {{
        "inf": "infinitive form",
        "present": "present tense",
        "past": "past tense",
        "future": "future tense"
    }},
    "examples": [
        "example sentence 1",
        "example sentence 2"
    ]
}}
'''
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a helpful assistant that creates Anki cards."},
            {"role": "user", "content": prompt}
        ]
    )
    try:
        card_data = json.loads(response.choices[0].message.content)
        return AnkiCard(**card_data)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Error parsing JSON from OpenAI: {e}")
        return None
