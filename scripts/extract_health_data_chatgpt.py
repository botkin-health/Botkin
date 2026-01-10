#!/usr/bin/env python3
"""
Извлечение данных из медицинских анализов через ChatGPT Vision API
Использует GPT-4 Vision для умного извлечения структурированных данных из PDF/изображений
"""

import sys
import json
from pathlib import Path
from typing import Dict, Optional, List
import base64

# Добавляем путь к telegram-bot для импорта api_key_loader
sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot" / "services"))
try:
    from chatgpt_vision import get_openai_api_key, encode_image
except ImportError:
    print("⚠️  Не удалось импортировать chatgpt_vision, используем прямую загрузку ключа")
    import os
    def get_openai_api_key() -> Optional[str]:
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key and api_key.strip() and api_key != "your_openai_key_here":
            return api_key.strip()
        key_file = Path(__file__).parent.parent / '.openai_api_key'
        if key_file.exists():
            try:
                return key_file.read_text().strip()
            except:
                pass
        return None


def pdf_to_images_for_chatgpt(pdf_path: Path) -> List[bytes]:
    """Конвертирует PDF в изображения для ChatGPT Vision"""
    try:
        import pypdfium2 as pdfium
        from PIL import Image
        import io
        
        pdf = pdfium.PdfDocument(str(pdf_path))
        images = []
        
        for page_num in range(len(pdf)):
            page = pdf.get_page(page_num)
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            
            img_bytes = io.BytesIO()
            pil_image.save(img_bytes, format='PNG')
            images.append(img_bytes.getvalue())
        
        pdf.close()
        return images
    except Exception as e:
        print(f"❌ Ошибка конвертации PDF: {e}")
        return []


def extract_health_data_with_chatgpt(file_path: Path, api_key: Optional[str] = None) -> Optional[Dict]:
    """
    Извлекает структурированные данные из медицинского анализа через ChatGPT Vision
    
    Args:
        file_path: Путь к PDF или изображению
        api_key: OpenAI API ключ
        
    Returns:
        Словарь с извлеченными данными
    """
    if not api_key:
        api_key = get_openai_api_key()
    
    if not api_key:
        print("❌ OpenAI API ключ не найден")
        return None
    
    try:
        import requests
    except ImportError:
        print("❌ Библиотека requests не установлена")
        return None
    
    # Определяем тип файла
    if file_path.suffix.lower() == '.pdf':
        print(f"📄 Конвертация PDF в изображения: {file_path.name}...")
        images = pdf_to_images_for_chatgpt(file_path)
        if not images:
            return None
        print(f"   ✅ Конвертировано {len(images)} страниц")
    else:
        # Для изображений читаем напрямую
        with open(file_path, 'rb') as f:
            images = [f.read()]
    
    # Формируем промпт для извлечения данных
    prompt = """Проанализируй это изображение медицинского анализа (лабораторного исследования).

Извлеки ВСЕ данные в формате JSON:

{
  "test_type": "тип анализа (например: общий анализ крови, биохимия, гормоны, витамины, COVID-19 и т.д.)",
  "date": "дата анализа в формате YYYY-MM-DD",
  "laboratory": "название лаборатории",
  "patient_name": "ФИО пациента",
  "patient_birth_date": "дата рождения в формате YYYY-MM-DD",
  "values": {
    "название_показателя": {
      "value": число или строка,
      "unit": "единица измерения",
      "reference_range": "нормальные значения (если указаны)",
      "status": "норма/выше нормы/ниже нормы"
    }
  },
  "comments": "любые комментарии или заключения"
}

ВАЖНО:
- Извлеки ВСЕ числовые значения и показатели
- Сохрани точные названия показателей на русском языке
- Если есть отклонения от нормы, укажи status
- Верни ТОЛЬКО валидный JSON, без markdown блоков и дополнительного текста
- Если дата указана в формате DD.MM.YYYY, конвертируй в YYYY-MM-DD"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    all_extracted_data = []
    
    # Обрабатываем каждую страницу
    for page_num, image_bytes in enumerate(images):
        print(f"   🤖 Обработка страницы {page_num + 1}/{len(images)} через ChatGPT Vision...")
        
        # Кодируем изображение
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.1
        }
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content'].strip()
                
                # Убираем markdown блоки если есть
                if content.startswith('```'):
                    lines = content.split('\n')
                    content = '\n'.join(lines[1:-1]) if len(lines) > 2 else content
                    content = content.strip()
                
                # Парсим JSON
                try:
                    data = json.loads(content)
                    all_extracted_data.append(data)
                    print(f"      ✅ Данные извлечены со страницы {page_num + 1}")
                except json.JSONDecodeError as e:
                    print(f"      ⚠️  Ошибка парсинга JSON: {e}")
                    print(f"      Ответ: {content[:300]}")
        except Exception as e:
            print(f"      ❌ Ошибка при запросе к ChatGPT API: {e}")
            continue
    
    # Объединяем данные со всех страниц
    if all_extracted_data:
        if len(all_extracted_data) == 1:
            return all_extracted_data[0]
        else:
            # Объединяем данные с нескольких страниц
            merged = all_extracted_data[0].copy()
            for page_data in all_extracted_data[1:]:
                # Объединяем values
                if 'values' in page_data:
                    merged.setdefault('values', {}).update(page_data['values'])
                # Объединяем комментарии
                if 'comments' in page_data:
                    merged['comments'] = (merged.get('comments', '') + '\n' + page_data['comments']).strip()
            return merged
    
    return None


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Извлечение данных из медицинских анализов через ChatGPT Vision')
    parser.add_argument('file', help='Путь к PDF или изображению')
    parser.add_argument('--output', '-o', help='Файл для сохранения результата (JSON)')
    parser.add_argument('--api-key', help='OpenAI API ключ')
    
    args = parser.parse_args()
    
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"❌ Файл не найден: {file_path}")
        sys.exit(1)
    
    print(f"🔍 Извлечение данных из {file_path.name}...")
    data = extract_health_data_with_chatgpt(file_path, args.api_key)
    
    if data:
        if args.output:
            output_path = Path(args.output)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ Данные сохранены в {output_path}")
        else:
            print("\n" + "="*60)
            print("ИЗВЛЕЧЕННЫЕ ДАННЫЕ:")
            print("="*60)
            print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("❌ Не удалось извлечь данные")


