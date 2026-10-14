# Local addition (WasimIbKhan/MinerU local-patches-v4, not upstream).
#
# Two docvortex heading fixes for DOCX:
#
# - A paragraph style whose id or name merely contains "heading" (Myheading2,
#   HeadingInvisNum) stops the style-chain search, so a style based on a real
#   "heading 2" is read as body text or as a heading at the wrong level. When
#   that first match is not a recognisable "Heading N", keep looking down the
#   basedOn chain, then at the outline level.
# - A heading does not end an open list, so list items after the heading are
#   appended to the list block before it and come out ahead of their heading.

from __future__ import annotations

from typing import Any

from loguru import logger


def _resolve_heading(converter: Any, paragraph: Any) -> tuple[str, int | None] | None:
    for style in converter._iter_style_chain(converter._get_paragraph_style(paragraph)):
        for candidate in (getattr(style, "style_id", None), getattr(style, "name", None)):
            if candidate and "heading" in candidate.lower():
                label, level = converter._get_heading_and_level(candidate)
                if label == "Heading":
                    return label, level
    outline = converter._get_effective_outline_level(paragraph)
    return ("Heading", outline + 1) if outline is not None else None


def install() -> None:
    try:
        from docvortex.analyzers.native.office.docx.docx_converter import DocxConverter
        from docx.text.paragraph import Paragraph
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"docx heading fixes disabled: {exc}")
        return
    if getattr(DocxConverter, "_docx_headings_installed", False):
        return
    label_and_level = DocxConverter._get_label_and_level
    handle_text = DocxConverter._handle_text_elements

    def get_label_and_level(self: Any, paragraph: Any) -> tuple[str, int | None]:
        label, level = label_and_level(self, paragraph)
        if label in ("Heading", "Title") or "heading" not in (label or "heading").lower():
            return label, level
        return _resolve_heading(self, paragraph) or (label, level)

    def handle_text_elements(self: Any, element: Any) -> Any:
        if self.pre_num_id != -1 and DocxConverter._local_name(element) == "p":
            paragraph = Paragraph(element, self.docx_obj)
            label, _ = self._get_label_and_level(paragraph)
            numid, _ = self._get_numId_and_ilvl(paragraph)
            if label in ("Title", "Heading") or ("Heading" in label and not numid):
                self._close_active_list()
        return handle_text(self, element)

    DocxConverter._get_label_and_level = get_label_and_level
    DocxConverter._handle_text_elements = handle_text_elements
    DocxConverter._docx_headings_installed = True


install()
