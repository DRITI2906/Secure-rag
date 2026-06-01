"""Smoke test: verifies the Groq API key works and the chosen model responds.

Run from the project root with the venv active (or its python directly):
    python scripts/smoke_groq.py

Reads GROQ_API_KEY and GROQ_MODEL from .env (never commit .env).
"""

import os
import sys

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

key = os.environ.get("GROQ_API_KEY", "").strip()
if not key:
    print("ERROR: GROQ_API_KEY is empty. Add it to .env (get a key at https://console.groq.com).")
    sys.exit(1)

model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

client = Groq(api_key=key)
resp = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": "Reply with exactly the word: ok"},
        {"role": "user", "content": "ping"},
    ],
    max_tokens=8,
    temperature=0,
)

print(f"model: {model}")
print(f"reply: {resp.choices[0].message.content!r}")
print(f"usage: prompt={resp.usage.prompt_tokens} completion={resp.usage.completion_tokens}")
