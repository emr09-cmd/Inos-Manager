import json
from google.genai import types
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

async def extract_memory(client, conversation_text: str, existing_profile: dict = None) -> dict:
    system_prompt = """
You are an expert memory extractor. 
Only return keys that match: nickname, personality, favorites, dislikes, projects, running_topics, known_friends, birthday, timezone.
Return valid JSON only.
"""

    safe_profile = existing_profile.copy() if existing_profile else {}
    if isinstance(safe_profile.get("last_seen"), datetime):
        safe_profile["last_seen"] = safe_profile["last_seen"].isoformat()

    prompt = f"""
Conversation:
{conversation_text}

Existing profile:
{json.dumps(safe_profile, indent=2, default=json_serializer) if safe_profile else "None"}

Extract important long-term information:
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                max_output_tokens=700
            )
        )
        text = response.text.strip()
        if text.startswith("```json"):
            text = text.split("```json")[1].split("```")[0]
        elif text.startswith("```"):
            text = text.split("```")[1]
        return json.loads(text)
    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")
        return {}