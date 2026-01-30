
import logging
import base64
import json
import re
import os
from pathlib import Path
from typing import Optional, Dict, Any

from core.api_key_loader import get_google_vision_api_key

logger = logging.getLogger(__name__)

def parse_weight_screenshot(file_paths: list[Path], api_key: Optional[str], description: str = "") -> Optional[Dict[str, Any]]:
    """
    Analyzes a screenshot (Zepp Life / Mi Fit) to extract weight and body metrics.
    Tries Google Gemini first (if api_key provided), then falls back to OpenAI GPT-4o.
    
    Args:
        file_paths: List of paths to image files.
        api_key: Gemini API Key (Optional).
        description: Optional context.
        
    Returns:
        Dict with metrics or None if not found.
    """
    
    # 1. Try Google Gemini
    if api_key:
        try:
            import google.generativeai as genai
            logger.info("Using Google Gemini for Weight OCR...")
            
            genai.configure(api_key=api_key)
            model_name = "gemini-1.5-flash"
            
            content = []
            prompt = _get_prompt()
            content.append(prompt)
            
            for path in file_paths:
                if not path.exists(): continue
                
                mime_type = _get_mime_type(path)
                with open(path, "rb") as f:
                    image_data = f.read()
                content.append({"mime_type": mime_type, "data": image_data})
                
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(content)
            
            data = _parse_json_response(response.text)
            if data and data.get('is_body_metrics') is True and 'weight' in data:
                return data
                
        except Exception as e:
            logger.error(f"Gemini OCR failed: {e}")
            # Fallthrough to OpenAI

    # 2. Try OpenAI GPT-4o
    # Use centralized loader to find key in files/.env
    try:
        from core.chatgpt_vision import get_openai_api_key
        openai_key = get_openai_api_key()
    except ImportError:
        openai_key = os.getenv("OPENAI_API_KEY")
        
    if openai_key:
        try:
            from openai import OpenAI
            logger.info("Using OpenAI GPT-4o for Weight OCR...")
            
            client = OpenAI(api_key=openai_key)
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _get_prompt()},
                    ]
                }
            ]
            
            # Add images
            for path in file_paths:
                if not path.exists(): continue
                b64_image = _encode_image(path)
                mime_type = _get_mime_type(path)
                image_url = f"data:{mime_type};base64,{b64_image}"
                
                messages[0]["content"].append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
            
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                response_format={ "type": "json_object" },
                max_tokens=300,
            )
            
            choice = response.choices[0]
            content = choice.message.content
            
            # Helper to clean keys
            raw_data = _parse_json_response(content)

            if raw_data and raw_data.get('is_body_metrics') is True:
                # Map keys to our standard schema
                mapped_data = _map_keys_to_standard(raw_data)
                if mapped_data and 'weight' in mapped_data:
                    return mapped_data

        except Exception as e:
            logger.error(f"OpenAI OCR failed: {e}")
    else:
        logger.warning("No OpenAI API Key found for fallback.")

    return None

def _get_prompt():
    return (
        "This is an OCR task for identifying body composition metrics (weight, body fat, etc.) "
        "usually from health apps like Zepp Life, Mi Fit, or Apple Health. "
        "IMPORTANT: If the image shows a restaurant menu, food descriptions, or prices, "
        "set 'is_body_metrics' to false and return an empty object for metrics. "
        "If it IS a body weight measurement, set 'is_body_metrics' to true and "
        "extract: weight (kg), bmi, body_fat (%), muscle_mass, water, visceral_fat, etc. "
        "Return a JSON object: {\"is_body_metrics\": bool, \"weight\": float, \"body_fat\": float, ...}."
    )

def _map_keys_to_standard(data: Dict[str, Any]) -> Dict[str, Any]:
    """Maps various label names to standard keys."""
    mapping = {
        'weight': ['weight', 'вес', 'вес тела'],
        'bmi': ['bmi', 'имт', 'индекс массы тела'],
        'body_fat': ['body fat', 'bodyfat', 'fat', 'телесный жир', 'жир', 'процент жира'],
        'muscle': ['muscle', 'muscles', 'muscle mass', 'мышцы', 'мышечная масса', 'процент мышц'],
        'water': ['water', 'body water', 'вода', 'процент воды', 'вода в организме'],
        'visceral_fat': ['visceral fat', 'visceral', 'висцеральный жир', 'уровень висцерального жира'],
        'bone_mass': ['bone mass', 'bone', 'костная масса', 'кости'],
        'bmr': ['bmr', 'basal metabolism', 'basal metabolic rate', 'основной обмен', 'калории', 'metabolism'],
        'protein': ['protein', 'белок', 'процент белка'],
        'date': ['date', 'time', 'дата', 'время'],
    }
    
    result = {}
    for k, v in data.items():
        k_lower = k.lower().strip()
        found = False
        for std_key, aliases in mapping.items():
            if k_lower in aliases or any(alias in k_lower for alias in aliases):
                # Clean value (remove units)
                val = v
                
                # Skip numeric cleaning for date
                if std_key == 'date':
                    result[std_key] = str(val)
                elif isinstance(val, str):
                    # Extract number for metrics
                    import re
                    match = re.search(r'[\d\.]+', val)
                    if match:
                        try:
                            val = float(match.group())
                        except ValueError:
                            pass
                    result[std_key] = val
                else:
                    result[std_key] = val
                    
                found = True
                break
        if not found:
            result[k] = v # Keep unknown keys too
            
    return result

def _get_mime_type(path: Path) -> str:
    if path.suffix.lower() == ".png": return "image/png"
    if path.suffix.lower() == ".webp": return "image/webp"
    return "image/jpeg"

def _encode_image(image_path: Path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def _parse_json_response(text: str) -> Optional[Dict]:
    try:
        text = text.strip()
        if text.startswith("```json"): text = text[7:]
        if text.startswith("```"): text = text[3:]
        if text.endswith("```"): text = text[:-3]
        return json.loads(text.strip())
    except Exception:
        return None
