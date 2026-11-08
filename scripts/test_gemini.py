import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.core.config import settings

H = {"x-goog-api-key": settings.gemini_api_key}
BASE = "https://generativelanguage.googleapis.com/v1beta"
CANDIDATES = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-lite-latest"]

REPORT = "bhai bus stand de kol takkar ho gayi, do bande zakhmi ne te ik gaadi vich fasya hoya"
PROMPT = ('Classify this emergency report. Return ONLY JSON like '
          '{"category":"accident","severity":"high"} with category in medical|accident|fire|rescue|other '
          'and severity in low|medium|high|critical. Report: ' + REPORT)

for model in CANDIDATES:
    t = time.monotonic()
    try:
        r = httpx.post(f"{BASE}/models/{model}:generateContent", headers=H, timeout=30,
                       json={"contents": [{"role": "user", "parts": [{"text": PROMPT}]}],
                             "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})
        took = time.monotonic() - t
        if r.status_code == 200:
            parts = r.json()["candidates"][0].get("content", {}).get("parts", [])
            out = "".join(p.get("text", "") for p in parts).strip()
            print(f"{model:28} 200 in {took:4.1f}s  -> {out[:90]}")
        else:
            print(f"{model:28} {r.status_code} in {took:4.1f}s  {r.text[:120]!r}")
    except Exception as exc:
        print(f"{model:28} FAILED after {time.monotonic() - t:.1f}s: {type(exc).__name__}")