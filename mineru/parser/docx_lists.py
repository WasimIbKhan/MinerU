# Local addition (WasimIbKhan/MinerU local-patches-v4, not upstream).
#
# docvortex turns a DOCX list into section headings when its items are
# interleaved with body text across more than one indent level. Exporters such
# as Google Docs reuse one bullet list for every bullet group in a document, so
# that guess turns every bullet into a heading. Paragraphs whose own style or
# properties carry an outline level are headings without it, so a list is only
# kept as headings when its numbering levels carry an outline level, directly or
# through a linked heading style.

from __future__ import annotations

from typing import Any

from loguru import logger

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _style_is_heading(converter: Any, style_id: str) -> bool:
    for style in converter.docx_obj.styles.element.iter(f"{_W}style"):
        if style.get(f"{_W}styleId") != style_id:
            continue
        name = style.find(f"{_W}name")
        label = f"{style_id} {name.get(f'{_W}val', '') if name is not None else ''}".lower()
        return "heading" in label or style.find(f"{_W}pPr/{_W}outlineLvl") is not None
    return False


def _carries_outline(converter: Any, numid: int) -> bool:
    for ilvl in range(9):
        level = converter._get_numbering_level_definition(numid, ilvl)
        if level is None:
            continue
        if level.find(f"{_W}pPr/{_W}outlineLvl") is not None:
            return True
        style = level.find(f"{_W}pStyle")
        if style is not None and _style_is_heading(converter, style.get(f"{_W}val", "")):
            return True
    return False


def install() -> None:
    try:
        from docvortex.analyzers.native.office.docx.numbering import _DocxNumbering
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"docx list-heading guard disabled: {exc}")
        return
    detect = _DocxNumbering._detect_heading_list_numids
    if getattr(detect, "_outline_guarded", False):
        return

    def detect_outlined_heading_lists(self: Any) -> set:
        return {numid for numid in detect(self) if _carries_outline(self, numid)}

    detect_outlined_heading_lists._outline_guarded = True
    _DocxNumbering._detect_heading_list_numids = detect_outlined_heading_lists


# docvortex starts a new top-level list whenever the numbering id changes, so a
# sub-list that uses its own numbering definition (common in Word and pandoc
# output) loses its depth. An item whose numId differs from the open list but
# sits deeper than an open list level nests under it, and an item that returns
# to an open level of its own numId continues that level.


def _owners(converter: Any) -> dict[int, int]:
    state = converter.__dict__.get("_list_block_numids")
    if state is None or state[0] is not converter.pages:
        state = converter._list_block_numids = (converter.pages, {})
    return state[1]


def _adopt_open_levels(converter: Any, numid: int, ilevel: int) -> None:
    owners = _owners(converter)
    kept = []
    for block in converter.list_block_stack:
        if block["ilevel"] < ilevel:
            kept.append(block)
        elif block["ilevel"] == ilevel and owners.get(id(block)) == numid:
            kept.append(block)
            break
        else:
            break
    if kept:
        converter.list_block_stack = kept
        converter.pre_num_id = numid
        converter.pre_ilevel = kept[-1]["ilevel"]


def install_nesting() -> None:
    try:
        from docvortex.analyzers.native.office.docx.numbering import _DocxNumbering
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"docx list nesting fix disabled: {exc}")
        return
    add_item = _DocxNumbering._add_list_item
    if getattr(add_item, "_nests_across_numids", False):
        return

    def add_list_item(self: Any, *, numid: int, ilevel: int, **kwargs: Any) -> Any:
        if self.pre_num_id not in (-1, numid) and self.list_block_stack:
            _adopt_open_levels(self, numid, ilevel)
        result = add_item(self, numid=numid, ilevel=ilevel, **kwargs)
        owners = _owners(self)
        for block in self.list_block_stack:
            owners.setdefault(id(block), numid)
        return result

    add_list_item._nests_across_numids = True
    _DocxNumbering._add_list_item = add_list_item


install()
install_nesting()
