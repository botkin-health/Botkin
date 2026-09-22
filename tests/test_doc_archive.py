"""Тесты безопасной распаковки ZIP для /doc (issue #499).

Архив — недоверённый ввод: покрываем zip-slip, zip-bomb, битый архив,
архив без подходящих файлов, смешанный архив, вложенные архивы, symlink,
лимит на число файлов.
"""

import io
import zipfile


from handlers.doc_archive import (
    ERROR_CORRUPT,
    ERROR_TOO_LARGE,
    ERROR_TOO_MANY_FILES,
    ERROR_ZIP_BOMB,
    MAX_FILES_IN_ARCHIVE,
    REASON_NESTED_ARCHIVE,
    REASON_PASSWORD_PROTECTED,
    REASON_SUSPICIOUS_RATIO,
    REASON_SYMLINK,
    REASON_UNSAFE_PATH,
    REASON_UNSUPPORTED_TYPE,
    extract_zip_safely,
)


def _make_zip(entries: dict[str, bytes], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_extracts_pdf_and_image_from_mixed_archive():
    """Смешанный архив: PDF и изображение достаются, посторонний .txt — тихо пропускается."""
    zip_bytes = _make_zip(
        {
            "biopsy.pdf": b"%PDF-1.4 fake pdf content",
            "photo.jpg": b"\xff\xd8\xff fake jpeg",
            "readme.txt": b"not medical",
        }
    )
    result = extract_zip_safely(zip_bytes)

    assert result.error is None
    names = {f.name for f in result.files}
    assert names == {"biopsy.pdf", "photo.jpg"}
    assert result.skipped[REASON_UNSUPPORTED_TYPE] == 1


def test_archive_with_no_suitable_files():
    """Архив без единого PDF/изображения — пустой список files, но не ошибка."""
    zip_bytes = _make_zip({"notes.txt": b"hello", "data.csv": b"a,b,c"})
    result = extract_zip_safely(zip_bytes)

    assert result.error is None
    assert result.files == []
    assert result.skipped[REASON_UNSUPPORTED_TYPE] == 2


def test_corrupt_archive_does_not_raise():
    """Битый архив — понятная причина, не исключение."""
    result = extract_zip_safely(b"this is not a zip file at all")
    assert result.error == ERROR_CORRUPT
    assert result.files == []


def test_archive_too_large_rejected_before_parsing():
    from handlers import doc_archive

    big = b"x" * (doc_archive.MAX_ARCHIVE_BYTES + 1)
    result = extract_zip_safely(big)
    assert result.error == ERROR_TOO_LARGE


def test_zip_slip_parent_traversal_dropped():
    """../../etc/passwd — путь выходит за пределы корня, файл не извлекается."""
    zip_bytes = _make_zip({"../../etc/passwd": b"fake-pdf-ish", "ok.pdf": b"%PDF-real"})
    result = extract_zip_safely(zip_bytes)

    assert result.error is None
    assert [f.name for f in result.files] == ["ok.pdf"]
    assert result.skipped[REASON_UNSAFE_PATH] == 1


def test_zip_slip_absolute_path_dropped():
    zip_bytes = _make_zip({"/etc/passwd": b"fake"})
    result = extract_zip_safely(zip_bytes)
    assert result.error is None
    assert result.files == []
    assert result.skipped[REASON_UNSAFE_PATH] == 1


def test_zip_slip_windows_drive_path_dropped():
    zip_bytes = _make_zip({"C:\\Windows\\System32\\evil.pdf": b"fake"})
    result = extract_zip_safely(zip_bytes)
    assert result.error is None
    assert result.files == []
    assert result.skipped[REASON_UNSAFE_PATH] == 1


def test_symlink_entry_dropped():
    """ZipInfo с unix-режимом symlink в external_attr — не извлекаем."""
    import stat

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.pdf")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
        zf.writestr("real.pdf", "%PDF-real")
    result = extract_zip_safely(buf.getvalue())

    assert result.error is None
    assert [f.name for f in result.files] == ["real.pdf"]
    assert result.skipped[REASON_SYMLINK] == 1


def test_nested_archive_not_expanded():
    """Вложенный zip внутри zip — не разворачиваем, пропускаем."""
    inner = _make_zip({"inner.pdf": b"%PDF-inner"})
    zip_bytes = _make_zip({"nested.zip": inner, "top.pdf": b"%PDF-top"})
    result = extract_zip_safely(zip_bytes)

    assert result.error is None
    assert [f.name for f in result.files] == ["top.pdf"]
    assert result.skipped[REASON_NESTED_ARCHIVE] == 1


def test_too_many_files_in_archive_rejected():
    entries = {f"doc_{i}.pdf": b"%PDF-" + str(i).encode() for i in range(MAX_FILES_IN_ARCHIVE + 1)}
    zip_bytes = _make_zip(entries)
    result = extract_zip_safely(zip_bytes)
    assert result.error == ERROR_TOO_MANY_FILES


def test_zip_bomb_detected_via_streaming_cap():
    """Один файл, разжимающийся далеко за пределы допустимого объёма —
    архив компактный (маленький compress_size), но ratio выдаёт подделку:
    либо запись отсекается ещё до чтения (suspicious_ratio), либо, если бы
    метаданные были подделаны и не сработала ratio-эвристика, потоковое
    чтение всё равно оборвало бы разбор целиком (zip_bomb). В любом случае
    гигантский файл НЕ должен попасть в files."""
    from handlers import doc_archive

    huge = b"\x00" * (doc_archive.MAX_UNCOMPRESSED_TOTAL_BYTES + 1024 * 1024)
    # ZIP_DEFLATED на повторяющихся нулевых байтах даёт огромный ratio —
    # маленький архив, гигантское содержимое.
    zip_bytes = _make_zip({"bomb.pdf": huge})
    assert len(zip_bytes) < doc_archive.MAX_ARCHIVE_BYTES  # сам архив компактный

    result = extract_zip_safely(zip_bytes)
    assert result.files == []
    assert (
        result.error == ERROR_ZIP_BOMB
        or result.skipped[REASON_SUSPICIOUS_RATIO] >= 1
        or result.skipped["too_large_entry"] >= 1
    )


def test_zip_bomb_bypassing_ratio_heuristic_caught_by_streaming_cap(monkeypatch):
    """Если бы ratio-эвристика почему-то не сработала (например метаданные
    central directory подделаны так, что compress_size выглядит близким к
    file_size) — потоковое чтение с лимитом всё равно должно оборвать разбор,
    т.к. настоящий распакованный объём считается по факту читаемых байт, а не
    по заявленным метаданным."""
    from handlers import doc_archive

    # Отключаем оба пре-чтения фильтра (декларируемый размер и ratio), чтобы
    # изолированно проверить именно защиту через потоковый лимит при чтении.
    monkeypatch.setattr(doc_archive, "MAX_COMPRESSION_RATIO", 10**9)
    monkeypatch.setattr(doc_archive, "MAX_SINGLE_ENTRY_BYTES", 10**12)

    huge = b"\x00" * (doc_archive.MAX_UNCOMPRESSED_TOTAL_BYTES + 1024 * 1024)
    zip_bytes = _make_zip({"bomb.pdf": huge})

    result = extract_zip_safely(zip_bytes)
    assert result.error == ERROR_ZIP_BOMB
    assert result.files == []


def test_suspicious_ratio_entry_skipped_before_full_read():
    """Метаданные central directory уже показывают аномальный ratio —
    пропускаем запись как подозрительную, не читая её целиком."""

    repetitive = b"A" * (5 * 1024 * 1024)  # хорошо сжимается deflate'ом
    zip_bytes = _make_zip({"weird.pdf": repetitive, "ok.pdf": b"%PDF-real content, not repetitive %%%"})
    result = extract_zip_safely(zip_bytes)

    # Либо ratio-эвристика, либо fallback на "слишком много данных" — в
    # любом случае подозрительный файл не должен попасть в files как есть.
    assert "weird.pdf" not in {f.name for f in result.files}
    assert result.skipped[REASON_SUSPICIOUS_RATIO] >= 1 or result.error == ERROR_ZIP_BOMB


def test_archive_result_is_deterministic_for_same_input():
    zip_bytes = _make_zip({"a.pdf": b"%PDF-a"})
    r1 = extract_zip_safely(zip_bytes)
    r2 = extract_zip_safely(zip_bytes)
    assert [f.content for f in r1.files] == [f.content for f in r2.files]


def _mark_entry_encrypted(zip_bytes: bytes, filename: str) -> bytes:
    """Выставляет бит шифрования (general purpose flag bit 0) для записи
    `filename` прямо в байтах готового zip — `zipfile.writestr` сбрасывает
    `ZipInfo.flag_bits`, заданный до записи (проверено: после `writestr`
    остаётся только служебный UTF-8-бит), так что единственный способ
    получить в тесте запись, которую `zipfile` считает зашифрованной без
    реального шифрования (недоступного через stdlib), — патчить local file
    header и central directory header постфактум. Формат — PKWARE APPNOTE."""
    data = bytearray(zip_bytes)
    name_bytes = filename.encode()

    idx = 0
    while True:
        idx = data.find(b"PK\x03\x04", idx)  # local file header signature
        if idx == -1:
            break
        name_len = int.from_bytes(data[idx + 26 : idx + 28], "little")
        if bytes(data[idx + 30 : idx + 30 + name_len]) == name_bytes:
            flag_offset = idx + 6
            flag = int.from_bytes(data[flag_offset : flag_offset + 2], "little") | 0x1
            data[flag_offset : flag_offset + 2] = flag.to_bytes(2, "little")
        idx += 4

    idx = 0
    while True:
        idx = data.find(b"PK\x01\x02", idx)  # central directory header signature
        if idx == -1:
            break
        name_len = int.from_bytes(data[idx + 28 : idx + 30], "little")
        if bytes(data[idx + 46 : idx + 46 + name_len]) == name_bytes:
            flag_offset = idx + 8
            flag = int.from_bytes(data[flag_offset : flag_offset + 2], "little") | 0x1
            data[flag_offset : flag_offset + 2] = flag.to_bytes(2, "little")
        idx += 4

    return bytes(data)


def test_password_protected_entry_detected_via_flag_bits():
    """Парольный (зашифрованный) файл внутри архива — отдельная причина
    пропуска, не общий «не подходящий формат» (issue #499, ревью)."""
    zip_bytes = _make_zip({"secret.pdf": b"%PDF-secret", "open.pdf": b"%PDF-open"})
    zip_bytes = _mark_entry_encrypted(zip_bytes, "secret.pdf")

    result = extract_zip_safely(zip_bytes)

    assert result.error is None
    assert [f.name for f in result.files] == ["open.pdf"]
    assert result.skipped[REASON_PASSWORD_PROTECTED] == 1


def test_directory_entries_not_counted_toward_file_limit():
    """Windows при архивации папки кладёт в zip и записи-директории — они не
    должны считаться при проверке лимита числа файлов (issue #499, ревью):
    архив с ровно MAX_FILES_IN_ARCHIVE файлами внутри одной папки не должен
    отбиваться целиком как «слишком много файлов»."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/", "")  # запись-директория, как кладёт Windows
        for i in range(MAX_FILES_IN_ARCHIVE):
            zf.writestr(f"docs/doc_{i}.pdf", f"%PDF-{i}")
    result = extract_zip_safely(buf.getvalue())

    assert result.error is None
    assert len(result.files) == MAX_FILES_IN_ARCHIVE


def test_memory_limits_sized_for_low_ram_prod_server():
    """Лимиты подобраны под реальный прод (3.8 ГБ RAM, ~1.1 ГБ available) —
    регресс-guard, чтобы кто-то случайно не вернул старые 150/30 МБ."""
    from handlers import doc_archive

    assert doc_archive.MAX_UNCOMPRESSED_TOTAL_BYTES == 40 * 1024 * 1024
    assert doc_archive.MAX_SINGLE_ENTRY_BYTES == 20 * 1024 * 1024
