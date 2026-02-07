#!/usr/bin/env python3
"""
OCR с использованием Google Cloud Vision API для HealthVault
Адаптировано из FamilyDocs проекта
"""

import os
import sys
from pathlib import Path
from typing import Optional

def install_google_vision():
    """Устанавливает библиотеку Google Vision"""
    import subprocess
    print("📦 Установка google-cloud-vision...")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "google-cloud-vision", "pypdfium2", "Pillow", "requests"], 
                          capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ Установлено!")
        return True
    else:
        print(f"❌ Ошибка установки: {result.stderr}")
        return False

def pdf_to_images(pdf_path: Path) -> list:
    """Конвертирует PDF в изображения для OCR"""
    try:
        import pypdfium2 as pdfium
        from PIL import Image
        import io
        
        pdf = pdfium.PdfDocument(str(pdf_path))
        images = []
        
        for page_num in range(len(pdf)):
            page = pdf.get_page(page_num)
            # Рендерим страницу в изображение с высоким разрешением
            bitmap = page.render(scale=2.0)  # 2x для лучшего качества
            pil_image = bitmap.to_pil()
            
            # Конвертируем в bytes для Google Vision API
            img_bytes = io.BytesIO()
            pil_image.save(img_bytes, format='PNG')
            images.append(img_bytes.getvalue())
        
        pdf.close()
        return images
    except Exception as e:
        print(f"⚠️  Ошибка конвертации PDF: {e}")
        return []

def ocr_with_google_vision(file_path: Path, api_key: Optional[str] = None) -> str:
    """
    Распознает текст с помощью Google Cloud Vision API
    
    Args:
        file_path: Путь к файлу (PDF, JPG, PNG и т.д.)
        api_key: API ключ Google Cloud (если не указан, используется переменная окружения)
    
    Returns:
        Распознанный текст
    """
    try:
        import base64
        import requests
    except ImportError:
        print("❌ Библиотека requests не установлена, устанавливаю...")
        if not install_google_vision():
            return ""
        # Перезагружаем импорты
        import importlib
        import sys
        if 'requests' in sys.modules:
            importlib.reload(sys.modules['requests'])
        import base64
        import requests
    
    # Загружаем API ключ используя единую функцию
    try:
        # Пробуем импортировать единую функцию загрузки ключа
        import sys
        api_key_loader_path = Path(__file__).parent.parent / "telegram-bot" / "services" / "api_key_loader.py"
        if api_key_loader_path.exists():
            sys.path.insert(0, str(api_key_loader_path.parent))
            from api_key_loader import get_google_vision_api_key
            api_key = get_google_vision_api_key(api_key)
        else:
            # Fallback: старая логика
            if not api_key:
                key_file = Path(__file__).parent.parent / ".google_vision_api_key"
                if not key_file.exists():
                    family_docs_key = Path.home() / "FamilyDocs" / ".google_vision_api_key"
                    if family_docs_key.exists():
                        key_file = family_docs_key
                        print(f"📋 Используется API ключ из FamilyDocs")
                if key_file.exists():
                    try:
                        with open(key_file, 'r') as f:
                            api_key = f.read().strip()
                    except Exception:
                        pass
            if not api_key:
                import os
                api_key = os.getenv('GOOGLE_VISION_API_KEY')
    except Exception as e:
        print(f"⚠️  Ошибка загрузки ключа через api_key_loader: {e}")
        # Fallback: старая логика
        if not api_key:
            import os
            api_key = os.getenv('GOOGLE_VISION_API_KEY')
    
    # Валидация ключа
    if not api_key or api_key.strip() == "" or api_key == "your_google_vision_key_here":
        print("❌ API ключ не найден или не настроен!")
        print("💡 Создайте файл .google_vision_api_key в корне проекта или используйте --api-key")
        print("💡 Или установите переменную окружения GOOGLE_VISION_API_KEY")
        return ""
    
    api_key = api_key.strip()
    if len(api_key) < 20:
        print(f"⚠️  API ключ слишком короткий ({len(api_key)} символов), возможно неверный")
        return ""
    
    print(f"✅ API ключ готов к использованию (длина: {len(api_key)} символов)")
    
    try:
        # Для PDF конвертируем в изображения
        if file_path.suffix.lower() == '.pdf':
            print(f"🔍 Конвертация PDF в изображения: {file_path.name}...")
            images = pdf_to_images(file_path)
            if not images:
                print("❌ Не удалось конвертировать PDF")
                return ""
            
            print(f"   📄 Страниц: {len(images)}")
            all_text = []
            
            # Используем REST API для простоты
            url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
            
            for i, image_content in enumerate(images):
                print(f"   🔍 Распознавание страницы {i+1}/{len(images)}...")
                image_base64 = base64.b64encode(image_content).decode('utf-8')
                
                payload = {
                    "requests": [{
                        "image": {"content": image_base64},
                        "features": [{"type": "TEXT_DETECTION"}]
                    }]
                }
                
                try:
                    response = requests.post(url, json=payload, timeout=60)
                    response.raise_for_status()
                    result = response.json()
                    
                    if 'responses' in result and len(result['responses']) > 0:
                        if 'textAnnotations' in result['responses'][0]:
                            texts = result['responses'][0]['textAnnotations']
                            if texts:
                                all_text.append(texts[0]['description'])
                                print(f"      ✅ Распознано {len(texts[0]['description'])} символов")
                            else:
                                print(f"      ⚠️  Текст не найден на странице {i+1}")
                        elif 'error' in result['responses'][0]:
                            error = result['responses'][0]['error']
                            print(f"      ❌ Ошибка API: {error.get('message', 'Unknown error')}")
                except Exception as e:
                    print(f"      ❌ Ошибка при распознавании страницы {i+1}: {e}")
            
            if all_text:
                text = "\n\n--- Страница ---\n\n".join(all_text)
                print(f"✅ Всего распознано {len(text)} символов из {len(images)} страниц")
                return text
            else:
                print("❌ Не удалось распознать текст")
                return ""
        
        # Для изображений используем прямой подход
        with open(file_path, 'rb') as image_file:
            image_content = image_file.read()
        
        image_base64 = base64.b64encode(image_content).decode('utf-8')
        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
        
        payload = {
            "requests": [{
                "image": {"content": image_base64},
                "features": [{"type": "TEXT_DETECTION"}]
            }]
        }
        
        print(f"🔍 Распознавание {file_path.name}...")
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        if 'responses' in result and len(result['responses']) > 0:
            if 'textAnnotations' in result['responses'][0]:
                texts = result['responses'][0]['textAnnotations']
                if texts:
                    text = texts[0]['description']
                    print(f"✅ Распознано {len(text)} символов")
                    return text
            elif 'error' in result['responses'][0]:
                error = result['responses'][0]['error']
                print(f"❌ Ошибка API: {error.get('message', 'Unknown error')}")
                return ""
        
        print("⚠️  Текст не найден")
        return ""
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        if "credentials" in str(e).lower() or "authentication" in str(e).lower():
            print("\n💡 Нужно настроить API ключ:")
            print("   1. Создайте проект в Google Cloud Console")
            print("   2. Включите Cloud Vision API")
            print("   3. Создайте API ключ")
            print("   4. Сохраните в файл: echo 'ваш_ключ' > .google_vision_api_key")
        return ""

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='OCR с Google Cloud Vision API для HealthVault')
    parser.add_argument('file', help='Путь к файлу для распознавания')
    parser.add_argument('--api-key', help='Google Cloud Vision API ключ')
    parser.add_argument('--output', '-o', help='Файл для сохранения результата')
    
    args = parser.parse_args()
    
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"❌ Файл не найден: {file_path}")
        sys.exit(1)
    
    text = ocr_with_google_vision(file_path, args.api_key)
    
    if text:
        if args.output:
            output_path = Path(args.output)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f"\n✅ Текст сохранен в {output_path}")
        else:
            print("\n" + "="*60)
            print("РАСПОЗНАННЫЙ ТЕКСТ:")
            print("="*60)
            print(text[:2000])
            if len(text) > 2000:
                print(f"\n... (показано 2000 из {len(text)} символов)")
    else:
        print("❌ Не удалось распознать текст")

