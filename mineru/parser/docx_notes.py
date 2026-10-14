# Local addition (WasimIbKhan/MinerU local-patches-v4, not upstream).
#
# docvortex drops DOCX footnotes and endnotes: the reference run carries no
# text and footnotes.xml / endnotes.xml are never read. This writes a "[n]"
# marker where each reference sits and emits the note as a page_footnote block
# "[n] text", the schema docvortex already uses for ODF and RTF notes.
# Footnotes close the section that references them, endnotes close the
# document. Labels follow Word: footnotes 1, 2, 3 and endnotes i, ii, iii,
# unless settings.xml picks another format.

from __future__ import annotations

from typing import Any, Iterator

from loguru import logger

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{_W_NS}}}"
_REFERENCES = {f"{_W}footnoteReference": "footnote", f"{_W}endnoteReference": "endnote"}
_SEPARATORS = {"separator", "continuationSeparator", "continuationNotice"}
_DEFAULT_FORMATS = {"footnote": "decimal", "endnote": "lowerRoman"}
_ROMAN = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
          (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]


def _roman(number: int) -> str:
    out = ""
    for value, numeral in _ROMAN:
        count, number = divmod(number, value)
        out += numeral * count
    return out


def _format_label(number: int, fmt: str) -> str:
    if fmt == "lowerRoman":
        return _roman(number)
    if fmt == "upperRoman":
        return _roman(number).upper()
    if fmt in ("lowerLetter", "upperLetter"):
        letter = chr(ord("a") + (number - 1) % 26) * ((number - 1) // 26 + 1)
        return letter if fmt == "lowerLetter" else letter.upper()
    return str(number)


class _NotePart:
    """The document part, but with the notes part's relationships (for links)."""

    def __init__(self, document_part: Any, notes_part: Any) -> None:
        self._document_part = document_part
        self.rels = notes_part.rels

    def __getattr__(self, name: str) -> Any:
        return getattr(self._document_part, name)


class _NoteStory:
    def __init__(self, part: _NotePart) -> None:
        self.part = part


class _Notes:
    def __init__(self) -> None:
        self.labels: dict[tuple[str, str], str] = {}
        self.counts = {"footnote": 0, "endnote": 0}
        self.pending: dict[str, list[tuple[str, str]]] = {"footnote": [], "endnote": []}
        self.emitted: set[tuple[str, str]] = set()
        self.bodies: dict[tuple[str, str], tuple[Any, Any]] | None = None
        self.formats: dict[str, str] | None = None


def _state(converter: Any) -> _Notes:
    notes = getattr(converter, "_docx_notes", None)
    if notes is None:
        notes = converter._docx_notes = _Notes()
    return notes


def _formats(converter: Any, notes: _Notes) -> dict[str, str]:
    if notes.formats is None:
        notes.formats = dict(_DEFAULT_FORMATS)
        try:
            settings = converter.docx_obj.settings.element
            for kind in notes.formats:
                fmt = settings.find(f"{_W}{kind}Pr/{_W}numFmt")
                if fmt is not None and fmt.get(f"{_W}val"):
                    notes.formats[kind] = fmt.get(f"{_W}val")
        except Exception:  # noqa: BLE001
            pass
    return notes.formats


def _label(converter: Any, reference: Any) -> tuple[tuple[str, str], str]:
    notes = _state(converter)
    key = (_REFERENCES[reference.tag], reference.get(f"{_W}id", ""))
    if key not in notes.labels:
        notes.counts[key[0]] += 1
        notes.labels[key] = _format_label(notes.counts[key[0]], _formats(converter, notes)[key[0]])
    return key, notes.labels[key]


def _marker_run(text: str, paragraph: Any) -> Any:
    from docx.oxml.parser import OxmlElement
    from docx.text.run import Run

    run, t = OxmlElement("w:r"), OxmlElement("w:t")
    t.text = text
    run.append(t)
    return Run(run, paragraph)


def _bodies(converter: Any, notes: _Notes) -> dict[tuple[str, str], tuple[Any, Any]]:
    if notes.bodies is not None:
        return notes.bodies
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.parser import parse_xml

    notes.bodies = {}
    document_part = converter.docx_obj.part
    for rel in document_part.rels.values():
        kind = {RT.FOOTNOTES: "footnote", RT.ENDNOTES: "endnote"}.get(rel.reltype)
        if kind is None or rel.is_external:
            continue
        try:
            part = rel.target_part
            root = parse_xml(part.blob)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"docx {kind}s unreadable: {exc}")
            continue
        story = _NoteStory(_NotePart(document_part, part))
        for note in root.iterchildren(f"{_W}{kind}"):
            if note.get(f"{_W}type") not in _SEPARATORS:
                notes.bodies[(kind, note.get(f"{_W}id", ""))] = (note, story)
    return notes.bodies


def _note_block(converter: Any, key: tuple[str, str], label: str) -> dict | None:
    from docx.text.paragraph import Paragraph
    from docvortex.content.spans import append_text_span, extend_inline_spans, inline_span_plain_text
    from docvortex.schema import BlockType

    note, story = _bodies(converter, _state(converter)).get(key, (None, None))
    if note is None:
        return None
    body: list[dict] = []
    for element in note.iter(f"{_W}p"):
        spans = converter._normalize_text_block_content(
            converter._build_text_from_elements(converter._get_paragraph_elements(Paragraph(element, story)))
        )
        if inline_span_plain_text(spans).strip():
            if body:
                append_text_span(body, " ")
            extend_inline_spans(body, spans)
    if not body:
        return None
    content: list[dict] = []
    append_text_span(content, f"[{label}] ")
    extend_inline_spans(content, body)
    return {"type": BlockType.PAGE_FOOTNOTE, "content": content}


def _flush(converter: Any, kinds: tuple[str, ...]) -> None:
    notes = _state(converter)
    for kind in kinds:
        keys, notes.pending[kind] = notes.pending[kind], []
        for key in keys:
            try:
                block = _note_block(converter, key, notes.labels[key])
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"docx {kind} {key[1]} skipped: {exc}")
                continue
            if block is not None:
                converter.cur_page.append(block)


def _flush_unreferenced(converter: Any) -> None:
    """Notes referenced only where the body walk does not look (tables go
    through mammoth) still belong to the document."""
    notes = _state(converter)
    for kind, note_id in _bodies(converter, notes):
        key = (kind, note_id)
        if key not in notes.emitted:
            notes.emitted.add(key)
            if key not in notes.labels:
                notes.counts[kind] += 1
                notes.labels[key] = _format_label(notes.counts[kind], _formats(converter, notes)[kind])
            notes.pending[kind].append(key)
    _flush(converter, ("footnote", "endnote"))


def install() -> None:
    try:
        from docvortex.analyzers.native.office.docx.docx_converter import DocxConverter
        from docx.text.run import Run
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"docx notes disabled: {exc}")
        return
    if getattr(DocxConverter, "_docx_notes_installed", False):
        return
    reset = DocxConverter._reset_document_state
    inner_content = DocxConverter._iter_paragraph_inner_content
    handle_text = DocxConverter._handle_text_elements
    new_page = DocxConverter._start_new_page
    header_footer = DocxConverter._add_header_footer

    def reset_document_state(self: Any) -> None:
        reset(self)
        self._docx_notes = _Notes()

    def iter_paragraph_inner_content(self: Any, paragraph: Any, container: Any = None) -> Iterator[Any]:
        for item in inner_content(self, paragraph, container):
            if not isinstance(item, Run):
                yield item
                continue
            children = list(item._element)
            references = [child for child in children if child.tag in _REFERENCES]
            if not references:
                yield item
                continue
            marks = [_marker_run(f"[{_label(self, ref)[1]}]", paragraph) for ref in references]
            first_text = next((i for i, child in enumerate(children) if child.tag == f"{_W}t"), len(children))
            if children.index(references[0]) < first_text:
                yield from marks
                yield item
            else:
                yield item
                yield from marks

    def handle_text_elements(self: Any, element: Any) -> Any:
        notes = _state(self)
        for reference in element.iter(*_REFERENCES):
            key, _ = _label(self, reference)
            if key not in notes.emitted:
                notes.emitted.add(key)
                notes.pending[key[0]].append(key)
        return handle_text(self, element)

    def start_new_page(self: Any) -> None:
        _flush(self, ("footnote",))
        new_page(self)

    def add_header_footer(self: Any, docx_obj: Any) -> None:
        _flush(self, ("footnote", "endnote"))
        _flush_unreferenced(self)
        header_footer(self, docx_obj)

    DocxConverter._reset_document_state = reset_document_state
    DocxConverter._iter_paragraph_inner_content = iter_paragraph_inner_content
    DocxConverter._handle_text_elements = handle_text_elements
    DocxConverter._start_new_page = start_new_page
    DocxConverter._add_header_footer = add_header_footer
    DocxConverter._docx_notes_installed = True


install()
