from google import genai
import json
import os
from dotenv import load_dotenv
from pathlib import Path
from fastmcp import Client

# load env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "https://semiacademically-prehensile-karoline.ngrok-free.dev/sse",
)
MCP_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()

    # Handle fenced JSON blocks.
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return json.loads(candidate)

    # Fallback: parse the first object-like payload.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("Model did not return valid JSON.")


def _to_int(value, field_name: str) -> int:
    try:
        return int(round(float(value)))
    except Exception as exc:
        raise ValueError(f"Invalid numeric value for {field_name}: {value}") from exc


def _normalize_logs_result(logs_result) -> list[dict]:
    # Expected shape from your MCP tool is a raw list of dict rows.
    if isinstance(logs_result, list):
        return [item for item in logs_result if isinstance(item, dict)]

    # FastMCP CallToolResult may expose parsed output in structured_content.
    structured = getattr(logs_result, "structured_content", None)
    if isinstance(structured, list):
        return [item for item in structured if isinstance(item, dict)]
    if isinstance(structured, dict):
        data = structured.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

    # FastMCP CallToolResult may place JSON text in content items.
    content = getattr(logs_result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return [row for row in parsed if isinstance(row, dict)]
                except Exception:
                    continue

    # Some wrappers expose data directly.
    data_field = getattr(logs_result, "data", None)
    if isinstance(data_field, list):
        return [item for item in data_field if isinstance(item, dict)]

    # Some clients may wrap the tool output under a "data" key.
    if isinstance(logs_result, dict):
        data = logs_result.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

    # Last fallback for stringified payloads.
    if isinstance(logs_result, str):
        try:
            parsed = json.loads(logs_result)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except Exception:
            return []

    return []


async def run_agent(intent: str, message: str = "", telegram_id: int | None = None) -> dict:
    """Single agent entrypoint used by Telegram bot.

    intents:
    - health: check MCP server health tool
    - food: extract macros from message and persist via add_food_log
    - query: fetch today's food logs and summarize
    """

    if intent == "health":
        async with Client(MCP_SERVER_URL) as mcp_client:
            health_result = await mcp_client.call_tool("health", {})
        return {"intent": "health", "result": health_result}

    if intent == "query":
        if telegram_id is None:
            raise ValueError("telegram_id is required for query intent")

        async with Client(MCP_SERVER_URL) as mcp_client:
            logs_result = await mcp_client.call_tool(
                "get_today_food_logs", {"telegram_id": int(telegram_id)}
            )

        logs = _normalize_logs_result(logs_result)
        totals = {
            "calories": 0,
            "protein": 0,
            "carbs": 0,
            "fat": 0,
        }

        for item in logs:
            totals["calories"] += int(item.get("calories", 0) or 0)
            totals["protein"] += int(item.get("protein", 0) or 0)
            totals["carbs"] += int(item.get("carbs", 0) or 0)
            totals["fat"] += int(item.get("fat", 0) or 0)

        return {
            "intent": "query",
            "query": message,
            "count": len(logs),
            "totals": totals,
            "logs": logs,
        }

    if intent != "food":
        raise ValueError(f"Unsupported intent: {intent}")

    if telegram_id is None:
        raise ValueError("telegram_id is required for food intent")

    prompt = f"""
You are a nutrition extraction engine.

Task:
Extract ONE food entry from the user message and estimate macros.

Rules:
- Return ONLY valid JSON (no markdown, no extra text).
- JSON keys must be exactly: food, calories, protein, carbs, fat.
- food must be a short string summary of the meal.
- calories, protein, carbs, fat must be numbers.
- If uncertain, make the best practical estimate.

User message:
{message}
""".strip()

    response = client.models.generate_content(
        model=MCP_MODEL,
        contents=prompt,
    )

    parsed = _extract_json_object(response.text or "")
    payload = {
        "telegram_id": int(telegram_id),
        "food": str(parsed.get("food", "")).strip() or "Unknown food",
        "calories": _to_int(parsed.get("calories", 0), "calories"),
        "protein": _to_int(parsed.get("protein", 0), "protein"),
        "carbs": _to_int(parsed.get("carbs", 0), "carbs"),
        "fat": _to_int(parsed.get("fat", 0), "fat"),
    }

    try:
        async with Client(MCP_SERVER_URL) as mcp_client:
            insert_result = await mcp_client.call_tool("add_food_log", payload)
    except Exception as exc:
        error_text = str(exc).lower()
        if "foreign key" in error_text or "telegram_links" in error_text:
            raise ValueError(
                "Telegram is not linked to a user yet. Run /register email password first."
            ) from exc
        raise

    return {
        "intent": "food",
        "macros": {
            "food": payload["food"],
            "calories": payload["calories"],
            "protein": payload["protein"],
            "carbs": payload["carbs"],
            "fat": payload["fat"],
        },
        "saved": insert_result,
    }