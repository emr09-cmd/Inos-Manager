import json
from google.genai import types
import logging

logger = logging.getLogger(__name__)

async def extract_memory(client, conversation_text: str, existing_profile: dict = None) -> dict:
    system_prompt = """
You are an expert memory extractor. Extract only clear, long-term facts from the conversation.
Only extract facts that the user clearly stated.
Ignore jokes. Ignore sarcasm. Ignore assumptions.
Return valid JSON.
"""

    prompt = f"""
Conversation:
{conversation_text}

Existing profile:
{json.dumps(existing_profile or {}, indent=2) if existing_profile else "None"}

Extract important information:
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                max_output_tokens=600
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