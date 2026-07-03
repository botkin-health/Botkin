"""Справочник проверенных продуктов (#255) — нормализация и матчинг.

Слой между LLM-распознаванием и БД: нормализует имена продуктов и матчит
items из ответа LLM на записи verified_products (точные КБЖУ с этикетки).

Хранение — database.models.VerifiedProduct, CRUD — database.crud.
"""

import re

# Ё → Е и схлопывание любых разделителей: «Solvie  Protein-Barre» и
# «solvie protein barre» должны давать один ключ.
_NON_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


def normalize_product_name(name: str) -> str:
    """Каноническая форма имени продукта для точного матчинга.

    lower + ё→е + все не-буквенно-цифровые последовательности → один пробел.
    Единая точка нормализации: и запись (name_norm в БД), и поиск обязаны
    проходить через неё, иначе матчинг молча развалится.
    """
    if not name:
        return ""
    s = name.lower().replace("ё", "е")
    s = _NON_WORD_RE.sub(" ", s)
    return s.strip()
