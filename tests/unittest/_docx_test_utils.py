"""Shared helpers for the local DOCX patch tests (local-patches-v4)."""
import zipfile

from mineru.parser import parse

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def write_package(path, document: str, parts: dict[str, tuple[str, str]] | None = None) -> None:
    """Write a minimal DOCX by hand; `parts` maps word/<name>.xml to (relationship type, xml)."""
    parts = parts or {}
    overrides = "".join(
        f'<Override PartName="/word/{name}" ContentType="application/vnd.openxmlformats-officedocument.'
        f'wordprocessingml.{name[:-4]}+xml"/>'
        for name in parts
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="{_REL}/{rel_type}" Target="{name}"/>'
        for i, (name, (rel_type, _)) in enumerate(parts.items(), start=1)
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            f'wordprocessingml.document.main+xml"/>{overrides}</Types>',
        )
        package.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        package.writestr(
            "word/_rels/document.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>',
        )
        package.writestr("word/document.xml", document)
        for name, (_, xml) in parts.items():
            package.writestr(f"word/{name}", xml)


def parse_blocks(path) -> list[dict]:
    content = parse(str(path), tier="flash").structured_content()
    return [block for page in content["pages"] for block in page["blocks"]]
