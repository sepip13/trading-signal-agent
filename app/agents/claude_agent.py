import json
import anthropic
from app.core.config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are an expert trading analyst specializing in ICT (Inner Circle Trader) methodology.
Analyze the provided market data and generate a structured trading signal.

Respond ONLY with valid JSON in this exact format:
{
  "direction": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<concise technical reasoning, max 3 sentences>"
}"""


def generate_signal(market_data: dict) -> dict:
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Analyze this market data and generate a signal:\n{json.dumps(market_data, indent=2)}",
            }
        ],
    )
    raw = message.content[0].text.strip()
    return json.loads(raw)
