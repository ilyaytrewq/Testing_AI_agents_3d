from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


@pytest.mark.parametrize("page", PAGES, ids=[str(path.relative_to(ROOT)) for path in PAGES])
def test_local_links_resolve(page: Path) -> None:
    for block in MarkdownIt().parse(page.read_text(encoding="utf-8")):
        for token in block.children or []:
            if token.type not in {"link_open", "image"}:
                continue
            address = urlsplit(str(token.attrGet("href" if token.type == "link_open" else "src")))
            if address.scheme or address.netloc or not address.path:
                continue
            target = (page.parent / unquote(address.path)).resolve()
            assert target.is_relative_to(ROOT) and target.exists(), f"Broken link: {address.path}"
