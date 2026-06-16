"""add cgm_connections + glucose_readings (CGM глюкоза, #96)

Revision ID: cgm0glucose01
Revises: 711fd5e3f1e8
Create Date: 2026-06-16

Таблицы под интеграцию CGM (Abbott FreeStyle Libre 3 → LibreLinkUp):
- cgm_connections: маппинг follower patient_id → telegram_id;
- glucose_readings: точки глюкозы (mmol/L) с upsert по (user_id, ts).
RLS включается так же, как в baseline-ревизии — только на postgres
(sqlite-тесты гоняют create_all, не alembic-миграции).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "cgm0glucose01"
down_revision: Union[str, None] = "711fd5e3f1e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cgm_connections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["telegram_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_id", name="cgm_connections_patient_id_key"),
    )
    op.create_table(
        "glucose_readings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("trend", sa.SmallInteger(), nullable=True),
        sa.Column("source", sa.String(length=50), server_default="librelinkup", nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "ts", name="glucose_readings_user_id_ts_key"),
    )
    op.create_index("idx_glucose_user_ts", "glucose_readings", ["user_id", sa.literal_column("ts DESC")], unique=False)

    # Гранты + RLS для hv_app (postgres-only). Роль hv_app создаётся в baseline-ревизии.
    op.execute(
        """
        GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE cgm_connections TO hv_app;
        GRANT SELECT,USAGE ON SEQUENCE cgm_connections_id_seq TO hv_app;
        GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE glucose_readings TO hv_app;
        GRANT SELECT,USAGE ON SEQUENCE glucose_readings_id_seq TO hv_app;

        ALTER TABLE cgm_connections ENABLE ROW LEVEL SECURITY;
        ALTER TABLE glucose_readings ENABLE ROW LEVEL SECURITY;

        -- Обе политики сверяют app.user_id с владельцем. ВНИМАНИЕ: в glucose_readings
        -- это колонка user_id, в cgm_connections — telegram_id; обе ссылаются на
        -- users.telegram_id (один домен). Не путать при будущих миграциях.
        CREATE POLICY user_isolation ON glucose_readings TO hv_app
            USING ((user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));
        CREATE POLICY user_isolation ON cgm_connections TO hv_app
            USING ((telegram_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint));
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_isolation ON glucose_readings;")
    op.execute("DROP POLICY IF EXISTS user_isolation ON cgm_connections;")
    op.drop_index("idx_glucose_user_ts", table_name="glucose_readings")
    op.drop_table("glucose_readings")
    op.drop_table("cgm_connections")
