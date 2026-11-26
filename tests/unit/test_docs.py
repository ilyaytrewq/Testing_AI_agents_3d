from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]


@pytest.mark.parametrize("page", PAGES, ids=[str(path.relative_to(ROOT)) for path in PAGES])
def test_docs_metadata_references_and_local_links(page: Path) -> None:
    front, header, body = page.read_text(encoding="utf-8").split("---\n", 2)
    assert front == ""
    metadata = yaml.safe_load(header)
    assert metadata["title"] and metadata["description"]
    assert isinstance(metadata["references"], dict)
    for name, fingerprint in metadata["references"].items():
        source = (page.parent / name).resolve()
        assert source.is_relative_to(ROOT) and source != page
        assert sha256(source.read_bytes()).hexdigest() == fingerprint, f"Stale reference: {name}"

    for block in MarkdownIt().parse(body):
        for token in block.children or []:
            if token.type not in {"link_open", "image"}:
                continue
            address = urlsplit(str(token.attrGet("href" if token.type == "link_open" else "src")))
            if address.scheme or address.netloc or not address.path:
                continue
            target = (page.parent / unquote(address.path)).resolve()
            assert target.is_relative_to(ROOT) and target.exists(), f"Broken link: {address.path}"
