"""LLM Client - OpenAI > Claude > Gemini fallback"""
import logging
from app.core.config import OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY

logger = logging.getLogger(__name__)


async def llm_chat(system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
    """LLM 호출: OpenAI(gpt-4o) > Claude(claude-sonnet-4-5) > Gemini(gemini-2.0-flash) 순서로 시도"""

    # 1. OpenAI
    if OPENAI_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.warning(f"OpenAI failed: {e}")

    # 2. Anthropic Claude
    if ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            resp = await client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return resp.content[0].text
        except Exception as e:
            logger.warning(f"Claude failed: {e}")

    # 3. Google Gemini
    if GOOGLE_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GOOGLE_API_KEY)
            resp = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"{system_prompt}\n\n{user_message}",
            )
            return resp.text
        except Exception as e:
            logger.warning(f"Gemini failed: {e}")

    return "AI 서비스에 연결할 수 없습니다. API 키를 확인해주세요."
