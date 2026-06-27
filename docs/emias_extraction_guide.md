# Как скачать данные из ЕМИАС (lk.emias.mos.ru)

> Руководство для Claude Code — позволяет автоматически скачать все анализы,
> исследования и медицинские документы из личного кабинета ЕМИАС.

## Технические особенности сайта

- SPA на React, маршруты через React Router
- Аутентификация: JWT-токен в **`X-Access-JWT`** заголовке (НЕ `Authorization: Bearer`)
- Токен хранится в `localStorage('patient.web.v2.accessToken')`
- Токен истекает примерно через 30–60 секунд при ожидании (нельзя использовать в batch-циклах)
- **Решение**: использовать перехват `URL.createObjectURL` — страница сама делает запросы со своим токеном

## Ключевые API-эндпоинты

```
GET /api/1/documents/analyzes?ehrId={ehrId}&shortDateFilter=all_time&includeCovidTests=YES
GET /api/1/documents/research?ehrId={ehrId}&shortDateFilter=all_time
GET /api/3/document?ehrId={ehrId}&documentId={docId}&extendedScansType=YES&visualizationType=PRINT_FORM
POST /api/auth/1/refresh   (httpOnly cookie — можно вызвать только со страницы)
```

Где взять `ehrId`:
```javascript
// В консоли браузера (на странице lk.emias.mos.ru):
localStorage.getItem('patient.web.v2.ehrId')  // или
// В сетевых запросах (F12 → Network) — параметр ehrId в любом запросе к /api/
```

## Пошаговая инструкция

### Шаг 1: Авторизация

1. Открыть https://lk.emias.mos.ru в браузере Claude Code
2. Войти через Госуслуги или SMS (Клод НЕ вводит пароли — нужно авторизоваться вручную)
3. После входа страница открывается на `lk.emias.mos.ru/medical-records`

### Шаг 2: Получить список документов через API

```javascript
// В консоли браузера (MCP tool: javascript_tool)
const ehrId = localStorage.getItem('patient.web.v2.ehrId');  // получить ehrId
const token = localStorage.getItem('patient.web.v2.accessToken');

// Список анализов
const r = await fetch(`/api/1/documents/analyzes?ehrId=${ehrId}&shortDateFilter=all_time&includeCovidTests=YES`,
  { headers: { 'X-Access-JWT': token } });
const data = await r.json();
console.log(JSON.stringify(data.slice(0, 3)));  // первые 3 для проверки
```

### Шаг 3: Установить перехватчик PDF-блобов

Запустить **локальный HTTP-сервер** для приёма PDF:

```python
# /tmp/emias_receiver.py
import http.server, json, base64, os
from pathlib import Path

SAVE_DIR = Path("/tmp/emias_pdfs")
SAVE_DIR.mkdir(exist_ok=True)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(length))
        doc_id = body['docId'][:8]
        fname = f"{body['date']}_{doc_id}_{body['title'][:30].replace(' ', '_')}.pdf"
        (SAVE_DIR / fname).write_bytes(base64.b64decode(body['b64']))
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *a): pass

print("Receiver started on port 18765")
http.server.HTTPServer(('localhost', 18765), Handler).serve_forever()
```

```bash
python3 /tmp/emias_receiver.py &
```

Установить перехватчик в браузере (MCP `javascript_tool`):

```javascript
window._savedPDFs = {};
window._pendingDocId = null;
const orig = URL.createObjectURL.bind(URL);
URL.createObjectURL = function(blob) {
  const url = orig(blob);
  if (blob.type === 'application/pdf' && blob.size > 1000) {
    const docId = window._pendingDocId || 'unknown_' + Date.now();
    const reader = new FileReader();
    reader.onload = e => {
      fetch('http://localhost:18765', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          docId, b64: e.target.result.split(',')[1],
          date: window._pendingDate || 'unknown',
          title: window._pendingTitle || 'unknown'
        })
      });
    };
    reader.readAsDataURL(blob);
  }
  return url;
};
window._interceptInstalled = true;
```

### Шаг 4: Скачать каждый документ

На главной странице (`/medical-records`):

1. Развернуть раздел «МОИ АНАЛИЗЫ» → нажать «все время»
2. Для каждого документа в списке:

```javascript
// Установить ID перед кликом
window._pendingDocId = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx';
window._pendingDate = '2025-01-23';
window._pendingTitle = 'Название_анализа';

// Затем кликнуть иконку ↓ рядом с документом через MCP computer tool
// или найти и кликнуть через DOM:
document.querySelector('[data-doc-id="..."] button').click()
```

3. Подождать 2–3 секунды, PDF перехватится и уйдёт на localhost:18765

### Шаг 5: Для исследований (ЭКГ, рентген, спирометрия)

Раздел «МОИ ИССЛЕДОВАНИЯ» → «все время» → кликнуть иконку документа рядом с исследованием → откроется попап → нажать кнопку скачивания (↓) внизу попапа.

Для ЭКГ доступны два варианта:
- «Скачать заключение врача» — только текст
- «Скачать заключение + кардиограмму» — PDF с графиком ЭКГ (рекомендуется)

### Шаг 6: Скопировать файлы в HealthVault

```python
import shutil
from pathlib import Path

HEALTH = Path("/path/to/HealthVault/ИМЯ — Здоровье")
TMP = Path("/tmp/emias_pdfs")

# Схема именования: {тип}_{YYYY-MM-DD}_{lab}_{подтип}.pdf
for pdf in TMP.glob("*.pdf"):
    # Переименовать по схеме и скопировать в HEALTH
    shutil.copy2(pdf, HEALTH / new_name)
```

### Шаг 7: Распарсить значения через GPT-4o-mini

```bash
cd HealthVault-engine
python3 scripts/import/parse_lab_pdfs.py --dry-run  # показать что будет парситься
python3 scripts/import/parse_lab_pdfs.py            # парсить всё
```

## ehrId пользователей

| Пользователь | ehrId |
|---|---|
| Александр | `09399b7a-e190-427b-aab9-abe8648532ec` |
| family_user | *(получить при первом входе из localStorage)* |

## Что доступно в ЕМИАС

| Раздел | Содержимое |
|---|---|
| МОИ АНАЛИЗЫ | Лабораторные анализы (кровь, ОАМ, ПЦР, антитела) |
| МОИ ИССЛЕДОВАНИЯ | ЭКГ, рентген, спирометрия, УЗИ (если делалось в ГБУЗ) |
| МОИ ПРИЁМЫ | История визитов к врачам |
| МОИ ПРИВИВКИ | Вакцинации |
| МОИ БОЛЬНИЧНЫЕ | Листы нетрудоспособности |
| МОИ СПРАВКИ И МЕД. ЗАКЛЮЧЕНИЯ | Медицинские заключения (часто пусто) |
| МОИ РЕЦЕПТЫ | Льготные рецепты |
| МОИ НАПРАВЛЕНИЯ | Направления на анализы |
| МОИ ЗАПИСИ | Записи к врачу (активные) |

## Типичные проблемы

| Проблема | Решение |
|---|---|
| `401 AuthTokenExpired` | Использовать клик через UI, не прямой fetch |
| `400 Bad Request` на `/api/1/documents/analyzes` | Параметр `shortDateFilter=all_time`, не `period=ALL_TIME` |
| Список обрезается в виджете | Прокрутить DOM-контейнер через JS или скачать через прямой клик |
| PDF не перехватывается | Перезагрузить страницу и переустановить интерцептор |
| `PATH outside allowed roots` при `download_media` | Не указывать `file_path` в Telegram MCP |

## Важные заметки

- ЕМИАС показывает только анализы, сделанные в ГБУЗ Москвы (городские поликлиники)
- Частные лаборатории (Инвитро, Хеликс, Fdoctor) — только если направление было из ГБУЗ
- Анализы с 2024 года — ЕМИАС стал агрегировать данные из городских ЛПУ
- Фильтр по умолчанию «6 мес» — всегда переключать на «все время»

---

[← Документация Botkin — Index](INDEX.md)
