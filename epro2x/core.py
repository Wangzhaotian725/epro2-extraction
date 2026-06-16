"""
Core parsing for EasyEDA Pro / JLCEDA Pro `.epro2` projects.

An `.epro2` file is a ZIP archive containing:
  - project2.json            project metadata
  - <name>.epru              the actual design data (one big UTF-8 text stream)
  - IMAGE/...                thumbnails (ignored)

The `.epru` stream is a sequence of lines. Each line is:

    <head-json> || <body-json>

where `head` always has a "type" field. A line whose head type is "DOCHEAD"
starts a new *document*; every line after it (until the next DOCHEAD) belongs
to that document. Documents have a docType such as PCB, SCH, SCH_PAGE,
FOOTPRINT, SYMBOL, DEVICE, BOARD, BLOB.

The body may itself contain the "||" sequence inside JSON strings, so we only
split on the FIRST occurrence and rejoin the remainder before parsing.

This module is intentionally dependency-free (standard library only).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterator


def _parse_line(line: str) -> tuple[dict, Any]:
    """Parse one `.epru` line into (head_dict, body_obj).

    body_obj is a dict/list if it was valid JSON, the raw string if not,
    or None if there was no body.
    """
    parts = line.split("||", 1)
    head = json.loads(parts[0])
    body: Any = None
    if len(parts) > 1:
        raw = parts[1].rstrip("|")
        if raw.strip():
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = raw
    return head, body


@dataclass
class EpruDoc:
    """One document inside the `.epru` stream."""

    index: int
    doc_type: str | None
    uuid: str | None
    title: str | None = None
    # list of (head, body) tuples, in file order
    elements: list[tuple[dict, Any]] = field(default_factory=list)

    def of_type(self, *types: str) -> Iterator[tuple[dict, Any]]:
        """Yield (head, body) elements whose head 'type' is in `types`."""
        wanted = set(types)
        for head, body in self.elements:
            if head.get("type") in wanted:
                yield head, body

    def count_types(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for head, _ in self.elements:
            t = head.get("type")
            out[t] = out.get(t, 0) + 1
        return out


class Epro2Project:
    """Parsed representation of an `.epro2` project."""

    def __init__(self, project_meta: dict, docs: list[EpruDoc]):
        self.meta = project_meta
        self.docs = docs

    # ---- loading -------------------------------------------------------

    @classmethod
    def open(cls, path: str) -> "Epro2Project":
        """Open an `.epro2` (zip) file and parse its `.epru` stream."""
        meta: dict = {}
        epru_text: str | None = None
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith("project2.json"):
                    try:
                        meta = json.loads(zf.read(name).decode("utf-8"))
                    except Exception:
                        meta = {}
                elif name.endswith(".epru"):
                    epru_text = zf.read(name).decode("utf-8")
        if epru_text is None:
            raise ValueError(f"No .epru document stream found inside {path!r}")
        docs = cls._split_documents(epru_text)
        return cls(meta, docs)

    @staticmethod
    def _split_documents(text: str) -> list[EpruDoc]:
        docs: list[EpruDoc] = []
        cur: EpruDoc | None = None
        idx = -1
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                head, body = _parse_line(line)
            except json.JSONDecodeError:
                # Skip a line we cannot parse rather than abort the whole file.
                continue
            if head.get("type") == "DOCHEAD":
                idx += 1
                meta = body if isinstance(body, dict) else {}
                cur = EpruDoc(
                    index=idx,
                    doc_type=meta.get("docType"),
                    uuid=meta.get("uuid"),
                )
                docs.append(cur)
            if cur is not None:
                # capture document title from META element
                if head.get("type") == "META" and isinstance(body, dict):
                    cur.title = body.get("title") or cur.title
                cur.elements.append((head, body))
        return docs

    # ---- accessors -----------------------------------------------------

    def docs_of(self, doc_type: str) -> list[EpruDoc]:
        return [d for d in self.docs if d.doc_type == doc_type]

    @property
    def pcb(self) -> EpruDoc | None:
        d = self.docs_of("PCB")
        return d[0] if d else None

    @property
    def sch_pages(self) -> list[EpruDoc]:
        return self.docs_of("SCH_PAGE")

    def inventory(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.docs:
            t = d.doc_type or "UNKNOWN"
            out[t] = out.get(t, 0) + 1
        return out
