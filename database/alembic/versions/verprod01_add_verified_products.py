"""add verified_products table (#255)

Revision ID: verprod01
Revises: pat0token01
Create Date: 2026-07-03

Справочник проверенных продуктов: точные КБЖУ с этикетки для упакованных
продуктов, чтобы LLM-vision не оценивал один и тот же батончик заново при
каждом фото. user_id NULL = общая запись (видна всем), иначе — личная.

Уникальность — два частичных индекса (личные / общие), потому что обычный
UNIQUE не дедуплицирует строки с NULL user_id.

RLS: ОТКЛОНЕНИЕ от паттерна cgm0glucose01 — политика чтения
`user_id IS NULL OR user_id = app.user_id`, иначе общие записи были бы
невидимы агенту (hv_app). Запись (WITH CHECK) — только в свои строки.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "verprod01"
down_revision: Union[str, None] = "pat0token01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verified_products",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_norm", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"), nullable=True),
        sa.Column("barcode", sa.String(length=32), nullable=True),
        sa.Column("calories_per_100g", sa.Float(), nullable=False),
        sa.Column("protein_per_100g", sa.Float(), nullable=False),
        sa.Column("fats_per_100g", sa.Float(), nullable=False),
        sa.Column("carbs_per_100g", sa.Float(), nullable=False),
        sa.Column("fiber_per_100g", sa.Float(), nullable=True),
        sa.Column("portion_g", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("times_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "source IN ('user_correction','label_photo','manual','import')",
            name="verified_products_source_check",
        ),
    )
    op.create_index(
        "uq_verified_products_user_name",
        "verified_products",
        ["user_id", "name_norm"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_verified_products_global_name",
        "verified_products",
        ["name_norm"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index("idx_verified_products_barcode", "verified_products", ["barcode"])

    # Гранты + RLS для hv_app (роль создаётся в baseline-ревизии).
    op.execute(
        """
        GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE verified_products TO hv_app;
        GRANT SELECT,USAGE ON SEQUENCE verified_products_id_seq TO hv_app;

        ALTER TABLE verified_products ENABLE ROW LEVEL SECURITY;

        -- Чтение: свои записи + общие (user_id IS NULL). Это сознательное
        -- отклонение от строгого user_isolation других таблиц — общий
        -- справочник продуктов по дизайну виден всем (#255).
        -- Запись: только в свои строки (общие записи создаёт сид/оператор).
        CREATE POLICY user_isolation ON verified_products TO hv_app
            USING (
                user_id IS NULL
                OR user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint
            )
            WITH CHECK (
                user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint
            );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_isolation ON verified_products;")
    op.drop_index("idx_verified_products_barcode", table_name="verified_products")
    op.drop_index("uq_verified_products_global_name", table_name="verified_products")
    op.drop_index("uq_verified_products_user_name", table_name="verified_products")
    op.drop_table("verified_products")
