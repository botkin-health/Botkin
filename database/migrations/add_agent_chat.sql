-- Path X: unified bot — aiogram @Botkin_md_bot also answers conversational questions
-- via in-process Claude SDK call (same tools as NanoClaw MCP server).
--
-- See docs/projects/2026-05_nanoclaw-agent-bot/ for context.
-- Applied: 2026-05-20

-- Per-user system prompt for conversational agent (rich health context, family
-- anamnesis, lifestyle, goals). Owner of source: kept in sync with
-- /opt/nanoclaw/groups/<folder>/CLAUDE.local.md for the same user (manual sync
-- for now — see PLAN.md tech debt).
ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_system_prompt TEXT;

-- Conversation history for agent_chat service. Each row = one message in the
-- exchange (user / assistant / tool_use / tool_result). Used to build the
-- messages array for the next Anthropic API call (last N turns).
CREATE TABLE IF NOT EXISTS agent_conversations (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool_use', 'tool_result')),
    content     JSONB NOT NULL,
    -- For Anthropic tool_use blocks: store the tool_use_id so we can pair
    -- tool_result with the original call across turns.
    tool_use_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_conv_user_created
    ON agent_conversations(user_id, created_at DESC);

-- RLS: only the user's own conversation, plus server-side admin access via the
-- bot's connection (which doesn't set app.user_id).
ALTER TABLE agent_conversations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_conversations_self ON agent_conversations;
CREATE POLICY agent_conversations_self ON agent_conversations
    FOR ALL
    USING (
        current_setting('app.user_id', true) = '' OR
        current_setting('app.user_id', true)::bigint = user_id
    );
