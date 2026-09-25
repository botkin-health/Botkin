# core/health/doc_normalize.py
"""Нормализация результата разбора медицинского документа (#561).

Один вход — сырой ответ модели или уже сохранённый `documents[].extracted`, один
выход — нормализованный `extracted`. Правила детерминированные и идемпотентные:
повторный прогон по результату ничего не меняет, поэтому их можно переприменять к
хранимым документам без вызова модели. Экстрактор (`doc_extractor`) — только
промпт, вызов и разбор JSON.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Подписи дат, которые не являются датой исследования (#558): на бланках КДЛ
# «Дата печати» стоит рядом с «Датой взятия материала» и позже неё на дни.
_NON_STUDY_DATE_LABELS = ("печат", "выдач", "регистрац", "готов", "рожден")


def _check_date(raw: Any, label: Any = None, today: Optional[date] = None) -> tuple[Optional[str], Optional[str]]:
    """(ISO-дата, None) или (None, причина отказа): not_iso, print_or_issue_date, future."""
    try:
        parsed = date.fromisoformat(str(raw).strip())
    except ValueError:
        return None, "not_iso"
    if any(marker in str(label or "").casefold() for marker in _NON_STUDY_DATE_LABELS):
        return None, "print_or_issue_date"
    if parsed > (today or date.today()) + timedelta(days=1):
        # +1 день: сервер в UTC, а у пользователя в Москве/Израиле уже «завтра».
        return None, "future"
    return parsed.isoformat(), None


def sanitize_date(data: dict, today: Optional[date] = None) -> None:
    """Проверяет `date` ответа модели на месте; неподходящую — обнуляет.

    Причина отказа — в `_date_rejected` (для логов и превью): not_iso,
    print_or_issue_date (модель сама подписала дату как печать/выдачу), future.
    Дату не угадываем и не чиним — только отказываемся от явно неверной.
    """
    raw = data.get("date")
    if raw is None:
        return
    iso, reason = _check_date(raw, data.get("date_label"), today)
    if iso is not None:
        data["date"] = iso
        return
    logger.info("doc_normalize: дата %r (подпись %r) отброшена: %s", raw, data.get("date_label"), reason)
    data["date"] = None
    data["_date_rejected"] = reason


# Пустая ячейка сводной таблицы — не значение (модель иногда переносит прочерк).
_EMPTY_CELLS = frozenset({"", "—", "-", "–", "н/д", "нет"})


def _series_values(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): v for k, v in raw.items() if v is not None and not (isinstance(v, str) and v.strip() in _EMPTY_CELLS)
    }


def normalize_series(data: dict, today: Optional[date] = None) -> None:
    """Сводная таблица за несколько дат → `series` по одной записи на дату (#559).

    Элемент без ISO-даты или с будущей датой отбрасывается (дату не угадываем —
    «03.2023» не становится 1 марта), причины — в `_series_rejected`. Записи за
    одну дату склеиваются (совпавший ключ — первое значение). Вышла одна дата —
    это обычный документ: дата и значения поднимаются наверх, `series` убирается,
    и все читатели документа работают как раньше. Две и больше — верхние
    `date`/`values` описывают только то, что даты не имеет.
    """
    raw = data.pop("series", None)
    by_date: dict[str, dict[str, Any]] = {}
    rejected: list[str] = []

    def _add(iso: str, laboratory: Any, values: dict[str, Any], units: Any = None) -> None:
        entry = by_date.setdefault(iso, {"date": iso, "laboratory": None, "values": {}})
        if laboratory and not entry["laboratory"]:
            entry["laboratory"] = str(laboratory).strip() or None
        for key, value in values.items():
            if key in entry["values"]:
                continue
            entry["values"][key] = value
            # Своя единица строки (#559): в досье витамин D одной даты — нмоль/л,
            # остальных — нг/мл. Хранится только для ключей этой записи.
            if isinstance(units, dict) and units.get(key):
                entry.setdefault("units", {})[key] = str(units[key])

    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        values = _series_values(item.get("values"))
        if not values:
            continue
        iso, reason = _check_date(item.get("date"), None, today)
        if iso is None:
            rejected.append(f"{item.get('date')!r}: {reason}")
            continue
        _add(iso, item.get("laboratory"), values, item.get("units"))
    if rejected:
        logger.info("doc_normalize: строки сводной таблицы отброшены: %s", rejected)
        data["_series_rejected"] = rejected
    if not by_date:
        return

    top_values = data.get("values") if isinstance(data.get("values"), dict) else {}
    if data.get("date") and top_values:
        _add(data["date"], data.get("laboratory"), top_values)
        top_values = {}
    if len(by_date) == 1:
        (entry,) = by_date.values()
        data["date"] = entry["date"]
        data["values"] = {**top_values, **entry["values"]}
        data["laboratory"] = data.get("laboratory") or entry["laboratory"]
        if entry.get("units"):
            data["units"] = {**(data.get("units") if isinstance(data.get("units"), dict) else {}), **entry["units"]}
        return
    data["date"] = None
    data["values"] = top_values
    data["series"] = [by_date[d] for d in sorted(by_date)]


DOC_KINDS = ("lab_panel", "imaging", "smear_pcr", "doctor_note", "other")


def normalize_kind(data: dict) -> None:
    """Приводит doc_kind/doc_type/summary; у мазков и ПЦР отбрасывает числа (#558).

    Числа мазков («1–2 в п/зр», «> 50000») не являются измерениями — модель
    выдумывает под них ключи вроде `leukocytes`, а может назвать и `WBC`.
    Отброшенное остаётся в `_dropped_values` для логов. Нет doc_kind в ответе —
    поле не добавляем (старые записи и читатели без него работают как раньше).
    """
    raw_kind = data.get("doc_kind")
    if raw_kind is not None:
        kind = re.sub(r"[\s\-]+", "_", str(raw_kind).strip().lower())
        if kind in DOC_KINDS:
            data["doc_kind"] = kind
        else:
            # Незнакомый тип ≠ «other»: other не пишется в blood_tests, и настоящая
            # панель с опечаткой в типе молча пропала бы из динамики (ревью #560).
            logger.info("doc_normalize: незнакомый doc_kind %r — поле убрано", raw_kind)
            data.pop("doc_kind")
    for key in ("doc_type", "summary"):
        if key in data:
            text = str(data.get(key) or "").strip()
            data[key] = text or None
    if data.get("doc_kind") == "lab_panel" and data.get("summary") and (data.get("values") or data.get("series")):
        # Резюме анализов от модели не храним: она регулярно пишет «все показатели в
        # пределах нормы» при значениях выше нормы (кальций 1.33 при норме до 1.32,
        # RBC 6.18 при норме до 5.70), и никакой фильтр фраз её не догоняет — каждая
        # новая формулировка проходит. Значения лежат рядом, оценка — дело агента по
        # референсам. Бланк анализа без чисел (серология, «не обнаружено») резюме
        # сохраняет — это пересказ напечатанного. У УЗИ/мазков/заключений тоже (#558).
        data["summary"] = None
    values = data.get("values")
    if data.get("doc_kind") == "smear_pcr" and isinstance(values, dict) and values:
        logger.info("doc_normalize: у smear_pcr отброшены числа: %s", list(values))
        data["_dropped_values"] = values
        data["values"] = {}
    if data.get("doc_kind") == "smear_pcr" and data.get("series"):
        logger.info("doc_normalize: у smear_pcr отброшена сводная таблица (%d дат)", len(data["series"]))
        data["_dropped_series"] = data.pop("series")


# Z00–Z13 — обращения для осмотра, обследования, скрининга: не диагнозы, в медпрофиль
# не попадают (#558). Остальные Z — значимые состояния (Z95 стент, Z94 трансплантат,
# Z99.2 диализ, Z21 ВИЧ, Z34 беременность, Z79 длительная терапия) — их оставляем.
_Z_CODE_RE = re.compile(r"\bZ(?:0\d|1[0-3])(?:\.\d+)?\b")


def _filter_conditions(data: dict) -> None:
    """Убирает из conditions пункты с кодом Z00–Z13; убранное — в `_dropped_conditions`."""
    kept, dropped = [], []
    for item in data.get("conditions") or []:
        (dropped if _Z_CODE_RE.search(item) else kept).append(item)
    if dropped:
        logger.info("doc_normalize: коды Z убраны из диагнозов: %s", dropped)
        data["_dropped_conditions"] = dropped
    data["conditions"] = kept


# Известные несовпадения единицы бланка с канонической (kb_schema): (ключ, единица
# бланка без пробелов, casefold) → (множитель, каноническая единица). Только то, что
# встречалось на реальных бланках; незнакомое не «чиним» молча (#558).
# Ключи — в casefold: модель пишет и hs_CRP, и hsCRP, и crp.
_UNIT_CONVERSIONS: dict[tuple[str, str], tuple[float, str]] = {
    (key, unit): (10.0, "мг/л") for key in ("hs_crp", "hscrp", "crp") for unit in ("мг/дл", "mg/dl")
}
# Досье #559: 25-OH витамин D в нмоль/л (1 нг/мл = 2.496 нмоль/л), общий тестостерон
# в нг/мл (1 нг/мл = 3.467 нмоль/л) — строки одной таблицы в разных единицах.
_UNIT_CONVERSIONS.update(
    {
        (key, unit): (round(1 / 2.496, 6), "нг/мл")
        for key in ("vitamin_d", "vitamin_d3", "vitd", "vit_d")
        for unit in ("нмоль/л", "nmol/l")
    }
)
_UNIT_CONVERSIONS.update(
    {
        (key, unit): (3.467, "нмоль/л")
        for key in ("testosterone", "testosterone_total", "total_testosterone")
        for unit in ("нг/мл", "ng/ml")
    }
)


def _convert_units(data: dict) -> None:
    """Пересчитывает значения, напечатанные не в канонической единице (СРБ в мг/дл).

    Сделанные пересчёты — в `_unit_conversions`; единица пересчитанного ключа
    обновляется на каноническую, чтобы повторная обработка не умножила ещё раз.
    У сводной таблицы (#559) единица значения — своя у строки (`series[].units`),
    иначе общая `units`; общие единицы берутся в исходном виде для всех дат.
    """
    top_units = data.get("units") if isinstance(data.get("units"), dict) else {}
    original = dict(top_units)
    done: list[str] = []
    top_converted: dict[str, str] = {}

    def _apply(values: Any, units: dict, where: str) -> dict[str, str]:
        changed: dict[str, str] = {}
        if not isinstance(values, dict):
            return changed
        for key, raw in list(values.items()):
            unit = units.get(key)
            if unit is None or not isinstance(raw, (int, float)) or isinstance(raw, bool):
                continue
            rule = _UNIT_CONVERSIONS.get((str(key).casefold(), "".join(str(unit).split()).casefold()))
            if rule is None:
                continue
            factor, canon_unit = rule
            values[key] = round(raw * factor, 6)
            changed[key] = canon_unit
            done.append(f"{where}{key}: {unit} → {canon_unit} ×{factor:g}")
        return changed

    top_converted.update(_apply(data.get("values"), original, ""))
    for entry in data.get("series") or []:
        if not isinstance(entry, dict):
            continue
        own = entry.get("units") if isinstance(entry.get("units"), dict) else {}
        for key, canon_unit in _apply(entry.get("values"), {**original, **own}, f"{entry.get('date')} ").items():
            if key in own:
                own[key] = canon_unit
            else:
                top_converted[key] = canon_unit
    if top_converted and isinstance(data.get("units"), dict):
        data["units"].update(top_converted)
    if done:
        logger.info("doc_normalize: пересчёт единиц: %s", done)
        data["_unit_conversions"] = done


def _as_str_list(v) -> list[str]:
    """Безопасно привести значение к списку непустых строк. Не-список → []."""
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def normalize_extracted(data: dict[str, Any], today: Optional[date] = None) -> dict[str, Any]:
    """Применяет все правила к `data` на месте и возвращает его же.

    Порядок важен: series до типа (у мазков отбрасывается уже собранная таблица),
    тип до единиц (числа мазков не пересчитываются), списки до фильтра кодов Z.
    """
    sanitize_date(data, today)
    normalize_series(data, today)
    normalize_kind(data)
    _convert_units(data)
    data["allergies"] = _as_str_list(data.get("allergies"))
    data["conditions"] = _as_str_list(data.get("conditions"))
    _filter_conditions(data)
    return data
