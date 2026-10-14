"""Local patch (local-patches-v4): DOCX package repairs before docvortex reads it
(mineru/parser/docx_package.py)."""
import pytest

pytest.importorskip("docx")

from _docx_test_utils import W_NS, parse_blocks, write_package  # noqa: E402


def test_wordprocessingml_under_another_prefix_parses(tmp_path):
    document = (
        f'<ns0:document xmlns:ns0="{W_NS}"><ns0:body>'
        '<ns0:p><ns0:pPr><ns0:numPr><ns0:ilvl ns0:val="0"/><ns0:numId ns0:val="0"/></ns0:numPr></ns0:pPr>'
        "<ns0:r><ns0:t>Written by ElementTree</ns0:t></ns0:r></ns0:p>"
        "</ns0:body></ns0:document>"
    )
    path = tmp_path / "ns0.docx"
    write_package(path, document)

    assert [(b["type"], b["content"]) for b in parse_blocks(path)] == [("text", "Written by ElementTree")]

