#!/usr/bin/env python3
"""
LLM Router: Central intelligence for the bot.
Classifies messages (Text/Photo) and extracts structured data using GPT-4o.
"""

import json
import base64
import sys
import requests
import time
from pathlib import Path
from typing import List, Optional, Dict, Union

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings
from .models import parse_llm_response
import logging
from config.models import FOOD_TEXT_MODEL_ANTHROPIC, FOOD_TEXT_MODEL_OPENAI, VISION_MODEL_GEMINI

logger = logging.getLogger(__name__)


def get_openai_api_key() -> Optional[str]:
    """Получает OpenAI API ключ из .env (OPENAI_API_KEY)."""
    return get_settings().openai_api_key


def encode_image(image_path: Path) -> str:
    """Encodes image to base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


# Системный промпт роутера еды — core/llm/prompts/food_router_system.txt.
# Версия v2 (13.09.2026): ~11.7K символов вместо 37K. Eval на 111 реальных кейсах
# (scripts/eval/, эталон golden_v3.json): ккал в интервале 91% vs 86% у старого
# промпта на Sonnet 4.6, латентность p50 3.6 с vs 6.3 с, цена −48%. Правила из
# инцидентов (CASE B + MODIFIER, независимые веса, multi_food) сохранены — их
# фиксируют tests/test_router_prompt_rules.py и tests/test_multi_food.py.
SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "food_router_system.txt").read_text(encoding="utf-8")


def _known_products_block(user_id: Optional[int]) -> str:
    """Блок «проверенные продукты пользователя» (#255) для system-промпта.

    Пусто (нет user_id / нет записей / ошибка БД) → "" — промпт остаётся
    прежним, справочник не должен ломать распознавание.
    """
    if not user_id:
        return ""
    try:
        from core.food.verified_products import build_known_products_block

        return build_known_products_block(user_id)
    except Exception as e:
        logger.warning(f"verified products prompt block failed: {e}")
        return ""


def _is_claude_4x(model: str) -> bool:
    return "-4-" in model or model.endswith("-4")


def analyze_message_claude(
    text: str = None,
    image_paths: List[Union[str, Path]] = None,
    user_id: Optional[int] = None,
) -> Optional[Dict]:
    """
    Analyzes message content using Claude Sonnet with prompt caching.
    Primary LLM — highest accuracy, ~90% cheaper on repeated system prompt via caching.
    """
    api_key = get_settings().anthropic_api_key
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY missing, falling back to GPT-4o")
        return None

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
    }

    # User content: text + images
    user_content = []
    if image_paths:
        for p in image_paths:
            path_obj = Path(p)
            if path_obj.exists():
                b64 = encode_image(path_obj)
                user_content.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                    }
                )
    if text:
        user_content.append({"type": "text", "text": f"USER MESSAGE: {text}"})

    if not user_content:
        return None

    payload = {
        "model": FOOD_TEXT_MODEL_ANTHROPIC,
        "max_tokens": 2000,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # кешируем системный промпт (~2.2K токенов)
            }
        ],
        "messages": [{"role": "user", "content": user_content}],
    }
    # Sonnet 5 / Opus 5 / Fable отвергают sampling-параметры (400); temperature
    # оставляем только семейству 4.x. Haiku 4.5 не знает output_config.effort.
    # effort="low": простая классификация в JSON, иначе модель «передумывает».
    if _is_claude_4x(FOOD_TEXT_MODEL_ANTHROPIC):
        payload["temperature"] = 0.1
    if "haiku" not in FOOD_TEXT_MODEL_ANTHROPIC:
        payload["output_config"] = {"effort": "low"}
    # Проверенные продукты (#255) — отдельным system-блоком БЕЗ cache_control:
    # per-user контент не должен ломать кеш базового SYSTEM_PROMPT.
    products_block = _known_products_block(user_id)
    if products_block:
        payload["system"].append({"type": "text", "text": products_block})

    for attempt in range(3):
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=45,
            )
            if response.status_code == 529 or response.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code >= 400 and "credit balance" in response.text.lower():
                from core.infra.owner_alerts import notify_owner_low_anthropic_balance

                notify_owner_low_anthropic_balance()
            response.raise_for_status()
            result = response.json()

            # Sonnet 5 на неоднозначных блюдах (бренды, несколько позиций,
            # «половина») сам включает extended thinking — тогда content[0]
            # это блок thinking, а JSON — в следующем text-блоке. Раньше код
            # брал content[0] безусловно и падал с KeyError('text'), уходя
            # в 3 бесполезных ретрая + fallback на GPT-4o (медленно).
            text_blocks = [
                block["text"] for block in result["content"] if isinstance(block, dict) and block.get("type") == "text"
            ]
            if not text_blocks:
                raise KeyError("no text block in Claude response content")
            content_str = text_blocks[0]
            # Извлечь JSON если обёрнут в markdown
            content_str = content_str.strip()
            if content_str.startswith("```"):
                content_str = content_str.split("\n", 1)[1]
                content_str = content_str.rsplit("```", 1)[0]

            cache_stats = result.get("usage", {})
            cached = cache_stats.get("cache_read_input_tokens", 0)
            created = cache_stats.get("cache_creation_input_tokens", 0)
            if cached or created:
                logger.info(f"Claude cache: read={cached} created={created} tokens")

            # Best-effort usage logging — non-blocking
            try:
                from core.llm_usage import log_anthropic_response

                purpose = "food_photo" if image_paths else "food_text"
                log_anthropic_response(
                    purpose=purpose,
                    model=payload.get("model", FOOD_TEXT_MODEL_ANTHROPIC),
                    response_json=result,
                    user_id=user_id,
                )
            except Exception:
                logger.exception("router: Claude usage logging failed")

            return parse_llm_response(json.loads(content_str))

        except requests.exceptions.HTTPError as e:
            logger.warning(f"Claude HTTP error (attempt {attempt + 1}): {e}")
            if attempt == 2:
                return None
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Claude error (attempt {attempt + 1}): {e}")
            if attempt == 2:
                return None
            time.sleep(1)

    return None


def analyze_message(
    text: str = None,
    image_paths: List[Union[str, Path]] = None,
    user_id: Optional[int] = None,
) -> Optional[Dict]:
    """
    Analyzes message content using Claude (primary) → GPT-4o → Gemini.
    Returns structured JSON or None on failure.

    user_id (optional) is threaded down so per-call costs in llm_usage_log
    are attributed to the right user instead of NULL.
    """
    # 1. Try Claude first
    result = analyze_message_claude(text, image_paths, user_id=user_id)
    if result is not None:
        return result
    logger.warning("Claude failed, falling back to GPT-4o...")

    # 2. Try GPT-4o
    api_key = get_openai_api_key()
    if not api_key:
        print("❌ OpenAI API Key missing")
        return None

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    # Build content list
    content = []

    # Add text if present
    if text:
        content.append({"type": "text", "text": f"USER MESSAGE: {text}"})

    # Add images if present
    if image_paths:
        for p in image_paths:
            path_obj = Path(p)
            if path_obj.exists():
                b64 = encode_image(path_obj)
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    if not content:
        return None

    # Construct payload
    system_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    products_block = _known_products_block(user_id)
    if products_block:
        system_messages.append({"role": "system", "content": products_block})
    payload = {
        "model": FOOD_TEXT_MODEL_OPENAI,
        "messages": system_messages + [{"role": "user", "content": content}],
        "max_tokens": 2000,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    # Retry logic
    for attempt in range(3):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30
            )

            if response.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue

            response.raise_for_status()
            result = response.json()

            content_str = result["choices"][0]["message"]["content"]
            if content_str is None:
                print(f"❌ OpenAI returned None content. Finish reason: {result['choices'][0].get('finish_reason')}")
                # Fallback to empty json to trigger retry or return None
                raise ValueError("OpenAI returned None content")

            parsed_json = json.loads(content_str)
            return parse_llm_response(parsed_json)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403 or e.response.status_code == 401:
                print(f"❌ OpenAI API {e.response.status_code} (Auth). Falling back to Gemini...")
                return analyze_message_gemini(text, image_paths, user_id=user_id)
            print(f"Error in LLM Router (Attempt {attempt + 1}): {e}")
            time.sleep(1)
        except requests.exceptions.ConnectionError:
            print("❌ OpenAI Connection Error. Falling back to Gemini...")
            return analyze_message_gemini(text, image_paths, user_id=user_id)
        except Exception as e:
            print(f"Error in LLM Router (Attempt {attempt + 1}): {e}")
            time.sleep(1)

    logger.warning(
        "LLM Router: OpenAI не ответил после всех попыток. "
        "Если бот пишет «OpenAI не отвечает» — возможно, закончились токены по ключу: доложи баланс в OpenAI."
    )
    return None


def analyze_message_gemini(
    text: str = None,
    image_paths: List[Union[str, Path]] = None,
    user_id: Optional[int] = None,
) -> Optional[Dict]:
    """
    Analyzes message content using Google Gemini (model from config/models.py; fallback for OpenAI).
    """
    settings = get_settings()
    api_key = settings.gemini_api_key or settings.google_api_key

    if not api_key:
        print("    ⚠️  Gemini API Key missing")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{VISION_MODEL_GEMINI}:generateContent?key={api_key}"

    headers = {"Content-Type": "application/json"}

    # Build parts
    parts = [{"text": SYSTEM_PROMPT}]
    products_block = _known_products_block(user_id)
    if products_block:
        parts.append({"text": products_block})
    if text:
        parts.append({"text": f"USER MESSAGE: {text}"})

    if image_paths:
        for p in image_paths:
            path_obj = Path(p)
            if path_obj.exists():
                with open(path_obj, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"},
    }

    print(f"    ✨ Attempting recognition through Gemini ({VISION_MODEL_GEMINI})...")

    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 429:
                wait = (attempt + 1) * 3
                logger.warning(f"Gemini 429 (rate limit), retry {attempt + 1}/3 через {wait} сек")
                time.sleep(wait)
                continue
            response.raise_for_status()
            result = response.json()

            content = result["candidates"][0]["content"]["parts"][0]["text"]
            # Clean markdown if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]

            return parse_llm_response(json.loads(content))
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429 and attempt < 2:
                wait = (attempt + 1) * 3
                logger.warning(f"Gemini 429 (rate limit), retry {attempt + 1}/3 через {wait} сек")
                time.sleep(wait)
                continue
            logger.warning(f"Gemini Fallback failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"Gemini Fallback failed: {e}")
            return None
    return None


if __name__ == "__main__":
    # Simple test
    test_text = "ужин: сырая морковь 100 г, варенная свекла 150 г, тунец 100 г"
    print(f"Testing with: {test_text}")
    print(json.dumps(analyze_message(text=test_text), indent=2, ensure_ascii=False))
