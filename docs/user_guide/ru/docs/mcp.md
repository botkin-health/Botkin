# Claude / Gemini через MCP

!!! warning "Скоро"
    Функция в разработке. Описание ниже — предварительное, JSON-примеры могут измениться. Следите за [журналом изменений](changelog.md).

## Что это и зачем

[MCP (Model Context Protocol)](https://modelcontextprotocol.io) — открытый стандарт, по которому AI-приложения (Claude Desktop, Gemini Desktop и другие) подключаются к внешним источникам данных.

Botkin предоставляет MCP-сервер `botkin-mcp`. Когда он подключён, можно спрашивать у Claude или Gemini вопросы вроде:

- «Как я поел на прошлой неделе?»
- «Какие добавки я принимал в апреле и какие пропускал?»
- «Сравни мой средний пульс покоя за март и за май.»

AI сам сходит в Botkin за данными, проанализирует и ответит.

## Шаг 1. Получить токен

Отправьте боту команду `/share`. В ответ придёт:

- персональный URL MCP-сервера (например, `https://mcp.botkin.health/u/abcd1234`);
- токен доступа.

Токен можно отозвать в любой момент той же командой.

## Шаг 2. Claude Desktop

Откройте `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Добавьте секцию `mcpServers`:

```json
{
  "mcpServers": {
    "botkin": {
      "command": "npx",
      "args": ["-y", "@botkin/mcp-client"],
      "env": {
        "BOTKIN_URL": "https://mcp.botkin.health/u/abcd1234",
        "BOTKIN_TOKEN": "ваш-токен-из-/share"
      }
    }
  }
}
```

Перезапустите Claude Desktop. В новом чате появится индикатор подключённого сервера `botkin`.

## Шаг 3. Gemini Desktop

Аналогично, в конфиге Gemini Desktop:

```json
{
  "mcp": {
    "servers": {
      "botkin": {
        "url": "https://mcp.botkin.health/u/abcd1234",
        "token": "ваш-токен-из-/share"
      }
    }
  }
}
```

## Безопасность

- Токен даёт доступ **только к вашим** данным.
- Запросы идут по HTTPS.
- Логи запросов доступны командой `/share status`.
- Отозвать доступ — `/share revoke`.
