# Local addition (WasimIbKhan/MinerU local-patches-v4, not upstream).
#
# Repairs to the DOCX package before docvortex reads it:
#
# - WordprocessingML bound to a prefix other than "w" (Python's ElementTree
#   writes "ns0:") is rebound to "w". Some docvortex lookups resolve "w:" through
#   the element's own nsmap and raise "prefix 'w' not found in prefix map".

from __future__ import annotations

import re
from io import BytesIO
from typing import Any
from zipfile import ZipFile

from loguru import logger
from lxml import etree

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W_PREFIXES = re.compile(rb'xmlns:([A-Za-z_][\w.-]*)\s*=\s*["\']' + re.escape(_W_NS.encode()) + rb'["\']')
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


def normalize_word_parts(file_bytes: bytes) -> bytes:
    from docvortex.analyzers.native.office.opc import write_zip_package

    with ZipFile(BytesIO(file_bytes)) as source:
        members, changed = [], False
        for info in source.infolist():
            data = source.read(info)
            if info.filename.endswith(".xml"):
                data, rewritten = _normalize_part(data)
                changed |= rewritten
            members.append((info, data))
    return write_zip_package(members) if changed else file_bytes


def _normalize_part(data: bytes) -> tuple[bytes, bool]:
    if not any(prefix != b"w" for prefix in _W_PREFIXES.findall(data)):
        return data, False
    try:
        root = etree.fromstring(data, _PARSER)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"docx part left as is, unparseable: {exc}")
        return data, False
    rebound = _rebind_w(root)
    if rebound is root:
        return data, False
    return etree.tostring(rebound, xml_declaration=True, encoding="UTF-8", standalone=True), True


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
