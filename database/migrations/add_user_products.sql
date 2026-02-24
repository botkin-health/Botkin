-- Таблица "мои продукты" и варианты для среднего КБЖУ
CREATE TABLE IF NOT EXISTS user_products (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    aliases JSONB,
    calories_per_100g FLOAT NOT NULL,
    protein_per_100g FLOAT NOT NULL,
    fats_per_100g FLOAT NOT NULL,
    carbs_per_100g FLOAT NOT NULL,
    default_portion_g FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_products_user ON user_products(user_id);

CREATE TABLE IF NOT EXISTS user_product_variants (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES user_products(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    calories_per_100g FLOAT NOT NULL,
    protein_per_100g FLOAT NOT NULL,
    fats_per_100g FLOAT NOT NULL,
    carbs_per_100g FLOAT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_variants_product ON user_product_variants(product_id);
