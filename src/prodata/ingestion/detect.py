"""Heurísticas de detecção de formato, encoding, delimitador e separador decimal."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

SAMPLE_BYTES = 64 * 1024

EXTENSIONS: dict[str, str] = {
    ".csv": "csv",
    ".txt": "csv",
    ".tsv": "csv",
    ".tab": "csv",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".xls": "excel",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".json": "json",
    ".ndjson": "ndjson",
    ".jsonl": "ndjson",
    ".arrow": "arrow",
    ".feather": "arrow",
    ".ipc": "arrow",
}

_DELIMITERS = [",", ";", "\t", "|"]
_COMMA_DECIMAL = re.compile(r"(?:^|[;\t|])\s*-?\d{1,3}(?:\.\d{3})*,\d+\s*(?=$|[;\t|])", re.MULTILINE)
_DOT_DECIMAL = re.compile(r"(?:^|[;\t|])\s*-?\d+\.\d+\s*(?=$|[;\t|])", re.MULTILINE)


def read_sample(path: Path, size: int = SAMPLE_BYTES) -> bytes:
    with path.open("rb") as fh:
        return fh.read(size)


def detect_format(path: Path) -> str:
    fmt = EXTENSIONS.get(path.suffix.lower(), "csv")
    if fmt == "json":
        return "ndjson" if _looks_like_ndjson(read_sample(path)) else "json"
    return fmt


def _looks_like_ndjson(sample: bytes) -> bool:
    lines = [ln for ln in sample.decode("utf-8", errors="ignore").splitlines() if ln.strip()]
    if len(lines) < 2 or not lines[0].lstrip().startswith("{"):
        return False
    try:
        json.loads(lines[0])
    except json.JSONDecodeError:
        return False
    return True


def detect_encoding(sample: bytes) -> str:
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # Ignora um possível caractere multibyte cortado no fim da amostra.
    trimmed = sample[:-4] if len(sample) >= SAMPLE_BYTES else sample
    try:
        trimmed.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8"


def sniff_delimiter(text: str) -> str:
    head = "\n".join(text.splitlines()[:50])
    try:
        return csv.Sniffer().sniff(head, delimiters="".join(_DELIMITERS)).delimiter
    except csv.Error:
        first = head.splitlines()[0] if head else ""
        return max(_DELIMITERS, key=first.count) if first else ","


def sniff_decimal(text: str, delimiter: str) -> str:
    """Retorna ',' quando os números do arquivo usam vírgula decimal (padrão brasileiro)."""
    if delimiter == ",":
        return "."
    normalized = text.replace(delimiter, ";") if delimiter != ";" else text
    comma = len(_COMMA_DECIMAL.findall(normalized))
    dot = len(_DOT_DECIMAL.findall(normalized))
    return "," if comma > dot else "."
