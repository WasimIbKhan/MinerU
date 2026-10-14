"""Local patch (local-patches-v4): a DOCX sub-list with its own numbering id stays
nested under the open list (mineru/parser/docx_lists.py)."""
import pytest

docx = pytest.importorskip("docx")
from docx.oxml import parse_xml  # noqa: E402

from _docx_test_utils import W_NS, parse_blocks  # noqa: E402


def _items_with_depth(markdown: str) -> list[tuple[int, str]]:
    lines = [line for line in markdown.splitlines() if line.strip()]
    return [((len(line) - len(line.lstrip())) // 4, line.strip().lstrip("-*0123456789. ")) for line in lines]


def test_sub_list_with_its_own_numbering_stays_nested(tmp_path):
    doc = docx.Document()
    numbering = doc.part.numbering_part.element
    for abstract_id in (91, 92):
        levels = "".join(f'<w:lvl w:ilvl="{i}"><w:numFmt w:val="bullet"/><w:lvlText w:val="o"/></w:lvl>'
                         for i in range(3))
        numbering.insert(0, parse_xml(
            f'<w:abstractNum xmlns:w="{W_NS}" w:abstractNumId="{abstract_id}">{levels}</w:abstractNum>'))
    outer, inner = numbering.add_num(91).numId, numbering.add_num(92).numId

    def item(text: str, num_id: int, ilvl: int) -> None:
        num_pr = doc.add_paragraph(text, style="List Paragraph")._p.get_or_add_pPr().get_or_add_numPr()
        num_pr.get_or_add_ilvl().val = ilvl
        num_pr.get_or_add_numId().val = num_id

    item("outer one", outer, 0)
    item("inner a", inner, 1)
    item("inner b", inner, 1)
    item("outer two", outer, 0)
    path = tmp_path / "nested_numids.docx"
    doc.save(path)

    lists = [b for b in parse_blocks(path) if b["type"] == "list"]
    assert len(lists) == 1
    assert _items_with_depth(lists[0]["content"]) == [(0, "outer one"), (1, "inner a"), (1, "inner b"), (0, "outer two")]
