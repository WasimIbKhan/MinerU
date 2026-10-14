"""Local patch (local-patches-v4): DOCX footnotes and endnotes become page_footnote
blocks with a [n] marker at the reference (mineru/parser/docx_notes.py)."""
import pytest

pytest.importorskip("docx")
from _docx_test_utils import W_NS, parse_blocks, write_package  # noqa: E402


def _run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def _notes(kind: str, notes: dict[int, str]) -> str:
    separator = f'<w:{kind} w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:{kind}>'
    bodies = "".join(f'<w:{kind} w:id="{note_id}"><w:p><w:r><w:{kind}Ref/></w:r>{_run(" " + text)}</w:p></w:{kind}>'
                     for note_id, text in notes.items())
    return f'<w:{kind}s xmlns:w="{W_NS}">{separator}{bodies}</w:{kind}s>'


def test_footnotes_and_endnotes_follow_their_references(tmp_path):
    document = (
        f'<w:document xmlns:w="{W_NS}"><w:body>'
        f'<w:p>{_run("Claim one.")}<w:r><w:footnoteReference w:id="2"/></w:r>'
        f'{_run(" Claim two.")}<w:r><w:endnoteReference w:id="5"/></w:r></w:p>'
        f'<w:p>{_run("Claim three.")}<w:r><w:footnoteReference w:id="7"/></w:r></w:p>'
        "</w:body></w:document>"
    )
    path = tmp_path / "notes.docx"
    write_package(path, document, {
        "footnotes.xml": ("footnotes", _notes("footnote", {2: "First source.", 7: "Second source."})),
        "endnotes.xml": ("endnotes", _notes("endnote", {5: "Closing remark."})),
    })

    assert [(b["type"], b["content"]) for b in parse_blocks(path)] == [
        ("text", "Claim one.[1] Claim two.[i]"),
        ("text", "Claim three.[2]"),
        ("page_footnote", "[1] First source."),
        ("page_footnote", "[2] Second source."),
        ("page_footnote", "[i] Closing remark."),
    ]
