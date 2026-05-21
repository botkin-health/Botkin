-- agent_review_consent: пользователь разрешает команде разработки читать
-- его переписку с BotkinClaw для product-review (поиск багов, feature requests,
-- расхождений ожиданий). Управляется тогглом в мини-аппе Настройки.
--
-- Default = TRUE: на текущей закрытой стадии (только семья + друзья) всем
-- проще держать включённым; явный opt-out возможен в любой момент.
-- Когда выйдем за пределы доверенного круга — default стоит переключить на
-- FALSE и просить consent в онбординге.
--
-- Применено: 2026-05-21

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS agent_review_consent BOOLEAN NOT NULL DEFAULT TRUE;


-- agent_conversations.source: маркер происхождения записи.
--   NULL          — легаси (всё что было до миграции)
--   'botkinclaw'  — реальный ход BotkinClaw (user→assistant→tools→assistant)
--   'router_food', 'router_vitamins', 'router_bp', 'router_weight',
--   'router_mixed', 'router_body_measurements' — raw текст пользователя,
--   который роутер угнал в специализированный обработчик (нутришн/витамины/...).
--   В историю BotkinClaw не подмешивается (см. core.agent_chat._load_history),
--   нужен только для product-review.
ALTER TABLE agent_conversations
    ADD COLUMN IF NOT EXISTS source TEXT;

CREATE INDEX IF NOT EXISTS idx_agent_conv_source
    ON agent_conversations(source) WHERE source IS NOT NULL;
