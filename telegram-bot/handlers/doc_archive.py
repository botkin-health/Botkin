# telegram-bot/handlers/doc_archive.py
"""Безопасная распаковка ZIP-архивов для /doc (issue #499).

Пожилой family-пользователь получает от Windows пачку документов, упакованную
в ZIP, а не по одному файлу — Explorer так всегда упаковывает выделенную группу
файлов при пересылке. Раньше бот такой архив просто не понимал.

Архив — недоверённый ввод. Всё здесь работает с сырыми байтами и не трогает
Telegram/FSM — легко тестировать в изоляции. Ограничения (см. issue #499,
раздел «Обязательные ограничения»):

- лимит на размер архива и на суммарный распакованный размер (zip-bomb);
- лимит на число файлов в архиве;
- пути вне корня (`../`, абсолютные, symlink) — zip-slip — отбрасываются;
- берём только PDF/изображения, остальное пропускаем молча (но считаем и
  сообщаем пользователю сколько и почему);
- вложенные архивы не разворачиваем;
- битый архив не роняет вызывающий код — возвращаем понятную причину.
"""

from __future__ import annotations

import stat
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from typing import Optional

# Telegram не отдаёт боту файлы тяжелее 20 МБ — это уже ограничивает входной
# архив, но проверяем явно и здесь на случай переиспользования кода не только
# из Telegram-пайплайна.
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024

# Суммарный РАСПАКОВАННЫЙ размер содержимого архива — основная защита от
# zip-bomb (маленький архив, разворачивающийся в гигабайты).
MAX_UNCOMPRESSED_TOTAL_BYTES = 150 * 1024 * 1024

# Один файл внутри архива после распаковки — не должен быть аномально большим
# (скан на 100 МБ — не медицинский документ, а подозрительная нагрузка).
MAX_SINGLE_ENTRY_BYTES = 30 * 1024 * 1024

# Разумный размер пачки документов от одного пользователя разом.
MAX_FILES_IN_ARCHIVE = 30

# Метаданные заявляют степень сжатия > 100x — подозрительно похоже на
# zip-bomb (например, deflate одного файла из нулевых байт). Проверяем ДО
# распаковки как быстрый эвристический фильтр — реальная защита всё равно
# идёт через потоковое чтение с лимитом ниже.
MAX_COMPRESSION_RATIO = 100

_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
_ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2"}

# Причины пропуска — используются и для подсчёта, и как ключи локализованных
# сообщений в doc_queue.py.
REASON_UNSUPPORTED_TYPE = "unsupported_type"
REASON_UNSAFE_PATH = "unsafe_path"
REASON_SYMLINK = "symlink"
REASON_NESTED_ARCHIVE = "nested_archive"
REASON_TOO_LARGE_ENTRY = "too_large_entry"
REASON_SUSPICIOUS_RATIO = "suspicious_ratio"

# Ошибки уровня всего архива (не пропуск отдельного файла, а отказ целиком).
ERROR_TOO_LARGE = "archive_too_large"
ERROR_CORRUPT = "corrupt_archive"
ERROR_TOO_MANY_FILES = "too_many_files"
ERROR_ZIP_BOMB = "zip_bomb"


@dataclass
class ExtractedFile:
    """Один файл, успешно и безопасно извлечённый из архива."""

    name: str  # исходное имя файла внутри архива (basename, без директорий)
    content: bytes
    ext: str
    is_pdf: bool


@dataclass
class ArchiveExtractionResult:
    files: list[ExtractedFile] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)  # reason -> count
    error: Optional[str] = None  # заполнено, если архив отклонён целиком


def _is_safe_member_path(name: str) -> bool:
    """True, если путь внутри архива не выходит за пределы корня распаковки."""
    if not name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    # Windows-путь с буквой диска (C:\...) — после замены `\`→`/` выглядит как
    # `C:/...`, PurePosixPath не считает это абсолютным путём, проверяем явно.
    if len(normalized) >= 2 and normalized[1] == ":":
        return False
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        return False
    return True


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """Символические ссылки в ZIP хранятся как unix-мод в старших 16 битах
    external_attr. На Windows-архивах external_attr обычно 0 — не symlink."""
    unix_mode = info.external_attr >> 16
    return stat.S_ISLNK(unix_mode) if unix_mode else False


def extract_zip_safely(content: bytes) -> ArchiveExtractionResult:
    """Разбирает ZIP-архив, отбрасывая всё небезопасное или неподходящее.

    Никогда не поднимает исключение наружу — любая проблема (битый архив,
    zip-bomb, слишком много файлов) возвращается через `.error`.
    """
    if len(content) > MAX_ARCHIVE_BYTES:
        return ArchiveExtractionResult(error=ERROR_TOO_LARGE)

    try:
        zf = zipfile.ZipFile(BytesIO(content))
        infolist = zf.infolist()
    except zipfile.BadZipFile:
        return ArchiveExtractionResult(error=ERROR_CORRUPT)
    except Exception:
        return ArchiveExtractionResult(error=ERROR_CORRUPT)

    if len(infolist) > MAX_FILES_IN_ARCHIVE:
        return ArchiveExtractionResult(error=ERROR_TOO_MANY_FILES)

    result = ArchiveExtractionResult()
    running_total = 0

    for info in infolist:
        try:
            if info.is_dir():
                continue
        except Exception:
            continue

        name = info.filename
        if not _is_safe_member_path(name):
            result.skipped[REASON_UNSAFE_PATH] += 1
            continue

        if _is_symlink_entry(info):
            result.skipped[REASON_SYMLINK] += 1
            continue

        basename = PurePosixPath(name.replace("\\", "/")).name
        ext = PurePosixPath(basename).suffix.lower()

        if ext in _ARCHIVE_EXTENSIONS:
            result.skipped[REASON_NESTED_ARCHIVE] += 1
            continue

        if ext not in _ALLOWED_EXTENSIONS:
            result.skipped[REASON_UNSUPPORTED_TYPE] += 1
            continue

        # Метаданные central directory могут быть подделаны, но это дешёвый
        # ранний фильтр до фактической распаковки — реальная защита (потоковый
        # лимит при чтении) идёт ниже независимо от того, сработал ли фильтр.
        if info.file_size > MAX_SINGLE_ENTRY_BYTES:
            result.skipped[REASON_TOO_LARGE_ENTRY] += 1
            continue

        compress_size = max(info.compress_size, 1)
        if (info.file_size / compress_size) > MAX_COMPRESSION_RATIO:
            result.skipped[REASON_SUSPICIOUS_RATIO] += 1
            continue

        try:
            data = _read_entry_with_cap(zf, info, MAX_SINGLE_ENTRY_BYTES)
        except _EntryTooLarge:
            result.skipped[REASON_TOO_LARGE_ENTRY] += 1
            continue
        except Exception:
            # Битая запись внутри архива — пропускаем как неподходящий файл,
            # не роняем разбор остальных (DoD issue #499).
            result.skipped[REASON_UNSUPPORTED_TYPE] += 1
            continue

        running_total += len(data)
        if running_total > MAX_UNCOMPRESSED_TOTAL_BYTES:
            # Суммарный объём содержимого архива вышел за разумные пределы —
            # похоже на zip-bomb. Отклоняем архив целиком: то, что уже
            # извлекли, не сохраняем частично — пользователь получит понятное
            # сообщение и сможет прислать документы по одному.
            return ArchiveExtractionResult(error=ERROR_ZIP_BOMB)

        is_pdf = ext == ".pdf"
        result.files.append(ExtractedFile(name=basename, content=data, ext=ext, is_pdf=is_pdf))

    return result


class _EntryTooLarge(Exception):
    """Внутренняя сигнализация: один файл в архиве при распаковке превысил
    допустимый размер — используется, чтобы прервать чтение немедленно,
    вместо того чтобы держать в памяти произвольно большой буфер."""


def _read_entry_with_cap(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    """Читает файл из архива потоково, обрывая чтение при превышении `cap`.

    Защищает от случая, когда central-directory метаданные (file_size) лгут,
    а реальный распакованный поток намного больше — python's zipfile не
    останавливается по file_size, а декомпрессирует до конца потока.
    """
    chunks: list[bytes] = []
    total = 0
    with zf.open(info) as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise _EntryTooLarge()
            chunks.append(chunk)
    return b"".join(chunks)
