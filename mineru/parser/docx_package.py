# Local addition (WasimIbKhan/MinerU local-patches-v4, not upstream).
#
# Repairs to the DOCX package before docvortex reads it:
#
# - WordprocessingML bound to a prefix other than "w" (Python's ElementTree
#   writes "ns0:") is rebound to "w". Some docvortex lookups resolve "w:" through
#   the element's own nsmap and raise "prefix 'w' not found in prefix map".
# - Content controls (w:sdt), except tables of contents, are replaced by their
#   w:sdtContent. docvortex reads a block-level control as a flat list of its
#   paragraphs, so tables inside it lose their structure, and drops the text of
#   one that also holds a picture. Unwrapping in the package, not the parsed
#   tree, keeps mammoth's table pre-parse aligned with the body walk.

from __future__ import annotations

import re
from io import BytesIO
from typing import Any, Callable
from zipfile import ZipFile

from loguru import logger
from lxml import etree

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{_W_NS}}}"
_W_PREFIXES = re.compile(rb'xmlns:([A-Za-z_][\w.-]*)\s*=\s*["\']' + re.escape(_W_NS.encode()) + rb'["\']')
_STORIES = {f"{_W}document", f"{_W}footnotes", f"{_W}endnotes"}
_TOC_STYLE = re.compile(r"^(toc|目录)\s*\d+$", re.IGNORECASE)
_PARSER = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True)


def _rebind_w(root: etree._Element) -> etree._Element:
    nsmap = dict(root.nsmap)
    if nsmap.get("w") not in (None, _W_NS):
        return root
    nsmap = {prefix: uri for prefix, uri in nsmap.items() if uri != _W_NS}
    nsmap["w"] = _W_NS
    rebound = etree.Element(root.tag, attrib=dict(root.attrib), nsmap=nsmap)
    rebound.text = root.text
    for child in list(root):
        rebound.append(child)
    return rebound


def _val(element: etree._Element | None) -> str:
    return element.get(f"{_W}val", "") if element is not None else ""


def _is_toc(sdt: etree._Element, style_names: Callable[[], dict[str, str]]) -> bool:
    """Same test as docvortex's _is_toc_sdt, which turns these into index blocks."""
    props = sdt.find(f"{_W}sdtPr")
    if props is not None:
        gallery = _val(props.find(f".//{_W}docPartGallery"))
        if "Table of Contents" in gallery or "toc" in gallery.lower():
            return True
        tag = _val(props.find(f"{_W}tag")).lower().replace(" ", "")
        if "toc" in tag or "contents" in tag:
            return True
    content = sdt.find(f"{_W}sdtContent")
    for paragraph in (content.findall(f"{_W}p") if content is not None else [])[:5]:
        style_id = _val(paragraph.find(f"{_W}pPr/{_W}pStyle"))
        if style_id and _TOC_STYLE.match(style_names().get(style_id, style_id)):
            return True
    return False


def _unwrap_sdts(root: etree._Element, style_names: Callable[[], dict[str, str]]) -> bool:
    changed = False
    for sdt in list(root.iter(f"{_W}sdt")):
        parent = sdt.getparent()
        if parent is None or _is_toc(sdt, style_names):
            continue
        content = sdt.find(f"{_W}sdtContent")
        index = parent.index(sdt)
        parent.remove(sdt)
        for offset, child in enumerate(list(content) if content is not None else []):
            parent.insert(index + offset, child)
        changed = True
    return changed


def _style_names(source: ZipFile) -> dict[str, str]:
    try:
        root = etree.fromstring(source.read("word/styles.xml"), _PARSER)
    except Exception:  # noqa: BLE001
        return {}
    return {
        style.get(f"{_W}styleId", ""): _val(style.find(f"{_W}name"))
        for style in root.iter(f"{_W}style")
    }


def normalize_word_parts(file_bytes: bytes) -> bytes:
    from docvortex.analyzers.native.office.opc import write_zip_package

    with ZipFile(BytesIO(file_bytes)) as source:
        names: dict[str, str] | None = None

        def style_names() -> dict[str, str]:
            nonlocal names
            if names is None:
                names = _style_names(source)
            return names

        members, changed = [], False
        for info in source.infolist():
            data = source.read(info)
            if info.filename.endswith(".xml"):
                data, rewritten = _normalize_part(data, style_names)
                changed |= rewritten
            members.append((info, data))
    return write_zip_package(members) if changed else file_bytes


def _normalize_part(data: bytes, style_names: Callable[[], dict[str, str]]) -> tuple[bytes, bool]:
    rebind = any(prefix != b"w" for prefix in _W_PREFIXES.findall(data))
    if not rebind and b"sdtContent" not in data:
        return data, False
    try:
        root = etree.fromstring(data, _PARSER)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"docx part left as is, unparseable: {exc}")
        return data, False
    rebound = _rebind_w(root) if rebind else root
    changed, root = rebound is not root, rebound
    if root.tag in _STORIES and _unwrap_sdts(root, style_names):
        changed = True
    if not changed:
        return data, False
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), True


def install() -> None:
    try:
        from docvortex.analyzers.native.office.docx.docx_converter import DocxConverter
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"docx package normalisation disabled: {exc}")
        return
    sanitize = DocxConverter._sanitize_missing_internal_relationships
    if getattr(sanitize, "_word_parts_normalized", False):
        return

    def sanitize_and_normalize(self: Any, file_bytes: bytes) -> bytes:
        file_bytes = sanitize(self, file_bytes)
        try:
            return normalize_word_parts(file_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"docx package normalisation skipped: {exc}")
            return file_bytes

    sanitize_and_normalize._word_parts_normalized = True
    DocxConverter._sanitize_missing_internal_relationships = sanitize_and_normalize


install()
