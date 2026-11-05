"""Da resposta da API para uma tabela: JSON, XML e CSV, com a amostra do documento mostrada na tela."""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

import polars as pl

from prodata.connectors.api_model import ApiDefinition, ApiError


def _dig(document: Any, path: str) -> Any:
    current = document
    for piece in [p for p in path.split(".") if p]:
        if isinstance(current, dict) and piece in current:
            current = current[piece]
        elif isinstance(current, list) and piece.isdigit() and int(piece) < len(current):
            current = current[int(piece)]
        else:
            return None
    return current


def _flatten(record: dict[str, Any], flatten: bool, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and flatten:
            out.update(_flatten(value, flatten, f"{name}."))
        elif isinstance(value, dict | list):
            out[name] = json.dumps(value, ensure_ascii=False)
        else:
            out[name] = value
    return out


def _explode(record: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """Uma linha por item da lista em ``path``; os demais campos se repetem. Lista vazia mantém a linha."""
    keys = [p for p in path.split(".") if p]
    parent: Any = record
    for key in keys[:-1]:
        parent = parent.get(key) if isinstance(parent, dict) else None
    items = parent.get(keys[-1]) if isinstance(parent, dict) and keys else None
    if not isinstance(items, list) or not items:
        return [record]
    rows = []
    for item in items:
        copy = json.loads(json.dumps(record))
        target = copy
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = item if isinstance(item, dict) else {"valor": item}
        rows.append(copy)
    return rows


def _as_records(found: Any) -> list[dict[str, Any]]:
    items = found if isinstance(found, list) else [found]
    return [i if isinstance(i, dict) else {"valor": i} for i in items if i is not None or len(items) == 1]


def _json_records(document: Any, d: ApiDefinition) -> list[dict[str, Any]]:
    if d.records_path:
        found = _dig(document, d.records_path)
        if found is None:
            keys = ", ".join(document) if isinstance(document, dict) else "uma lista"
            raise ApiError(f'O caminho "{d.records_path}" não existe na resposta. Ela traz: {keys[:200]}.')
    elif isinstance(document, dict):
        lists = [v for v in document.values() if isinstance(v, list)]
        found = lists[0] if len(lists) == 1 else document
    else:
        found = document
    rows = _as_records(found)
    if d.explode_path:
        rows = [r for row in rows for r in _explode(row, d.explode_path)]
    return [_flatten(r, d.flatten) for r in rows]


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element(el: ET.Element) -> Any:
    data: dict[str, Any] = {f"@{_strip_ns(k)}": v for k, v in el.attrib.items()}
    for child in el:
        name = _strip_ns(child.tag)
        value = _element(child)
        if name in data:
            data[name] = [*data[name], value] if isinstance(data[name], list) else [data[name], value]
        else:
            data[name] = value
    text = (el.text or "").strip()
    if not data:
        return text or None
    if text:
        data["valor"] = text
    return data


def _xml_records(body: bytes, d: ApiDefinition) -> list[dict[str, Any]]:
    if b"<!DOCTYPE" in body[:4096] or b"<!ENTITY" in body[:65536]:
        raise ApiError("A resposta XML traz um DOCTYPE, que não é aceito por segurança.")
    try:
        root = ET.fromstring(body)  # noqa: S314  (DOCTYPE e ENTITY já recusados acima)
    except ET.ParseError as exc:
        raise ApiError(f"A resposta não é um XML válido: {exc}.") from None
    node = root
    pieces = [p for p in d.records_path.split(".") if p]
    if pieces and pieces[0] == _strip_ns(root.tag):
        pieces = pieces[1:]
    for depth, piece in enumerate(pieces):
        matches = [c for c in node if _strip_ns(c.tag) == piece]
        if not matches:
            raise ApiError(f'O caminho "{d.records_path}" não existe na resposta.')
        if depth == len(pieces) - 1:
            return [_flatten(r, d.flatten) for r in _as_records([_element(m) for m in matches])]
        node = matches[0]
    # Sem caminho: desce até achar um elemento que se repete.
    while len(node) == 1:
        node = node[0]
    tags = Counter(_strip_ns(c.tag) for c in node)
    if not tags:
        return [_flatten(r, d.flatten) for r in _as_records(_element(node))]
    common = tags.most_common(1)[0][0]
    return [
        _flatten(r, d.flatten) for r in _as_records([_element(c) for c in node if _strip_ns(c.tag) == common])
    ]


def _csv_records(body: bytes) -> list[dict[str, Any]]:
    head = body[:4096].decode("utf-8", "replace").split("\n", 1)[0]
    separator = max(",;\t|", key=head.count)
    frame = pl.read_csv(
        io.BytesIO(body),
        separator=separator,
        infer_schema_length=10_000,
        truncate_ragged_lines=True,
        encoding="utf8-lossy",
        quote_char='"',
    )
    return frame.to_dicts()


def _detect_format(body: bytes, content_type: str, wanted: str) -> str:
    if wanted != "auto":
        return wanted
    kind = content_type.lower()
    if "json" in kind:
        return "json"
    if "xml" in kind:
        return "xml"
    if "csv" in kind:
        return "csv"
    if "html" in kind:
        raise ApiError(
            "A API devolveu uma página HTML, e não dados. Costuma ser uma tela de login: confira o endereço e a autenticação."
        )
    start = body.lstrip()[:1]
    return "json" if start in (b"{", b"[") else "xml" if start == b"<" else "csv"


def parse_records(body: bytes, content_type: str, d: ApiDefinition) -> tuple[list[dict[str, Any]], Any]:
    """Linhas da resposta e o documento JSON (para achar o próximo cursor)."""
    if not body.strip():
        return [], None
    kind = _detect_format(body, content_type, d.format)
    if kind == "json":
        try:
            document = json.loads(body)
        except ValueError:
            raise ApiError("A resposta não é um JSON válido.") from None
        return _json_records(document, d), document
    if kind == "xml":
        return _xml_records(body, d), None
    return _csv_records(body), None


def _column(name: str, values: list[Any]) -> pl.Series:
    kinds = {type(v) for v in values if v is not None}
    if kinds == {bool}:
        return pl.Series(name, values, dtype=pl.Boolean)
    if kinds == {int}:
        try:
            return pl.Series(name, values, dtype=pl.Int64)
        except (
            OverflowError,
            TypeError,
            pl.exceptions.PolarsError,
        ):  # número grande demais vira texto, sem arredondar
            return pl.Series(name, [None if v is None else str(v) for v in values], dtype=pl.String)
    if kinds and kinds <= {int, float}:
        return pl.Series(name, [None if v is None else float(v) for v in values], dtype=pl.Float64)
    return pl.Series(name, [None if v is None else _as_str(v) for v in values], dtype=pl.String)


SAMPLE_ITEMS = 3


SAMPLE_FIELDS = 30


SAMPLE_DEPTH = 6


SAMPLE_TEXT = 80


def sample_document(node: Any, path: str = "", depth: int = 0) -> dict[str, Any]:
    """Amostra da resposta para a tela (RF-2225): poucos itens por lista, textos curtos, profundidade limitada."""
    if isinstance(node, dict):
        fields = list(node.items())
        if depth >= SAMPLE_DEPTH:
            return {"kind": "more", "text": f"{len(fields)} campos"}
        shown = [
            [str(k), sample_document(v, f"{path}.{k}" if path else str(k), depth + 1)]
            for k, v in fields[:SAMPLE_FIELDS]
        ]
        return {"kind": "object", "fields": shown, "hidden": max(0, len(fields) - SAMPLE_FIELDS)}
    if isinstance(node, list):
        inner = f"{path}.*" if path else "*"
        items = (
            []
            if depth >= SAMPLE_DEPTH
            else [sample_document(v, inner, depth + 1) for v in node[:SAMPLE_ITEMS]]
        )
        return {"kind": "list", "path": path, "total": len(node), "items": items}
    if isinstance(node, str) and len(node) > SAMPLE_TEXT:
        return {"kind": "value", "value": node[:SAMPLE_TEXT] + "…", "path": path}
    return {"kind": "value", "value": node, "path": path}


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def rows_to_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Colunas na ordem em que aparecem; tipos misturados viram texto, para nada se perder."""
    names = list(dict.fromkeys(k for r in rows for k in r))
    return pl.DataFrame([_column(n, [r.get(n) for r in rows]) for n in names])
