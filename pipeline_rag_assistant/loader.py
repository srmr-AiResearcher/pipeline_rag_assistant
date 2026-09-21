"""
Block loader — generalized to accept ANY blocks directory, not a
hardcoded path. This is the core generalization that makes this an
open-source TOOL rather than a one-off demo: users point this at
their OWN library of pipeline blocks (their org's real, verified
templates), and everything downstream works unchanged.

Falls back to the bundled `example_blocks/` (12 blocks: Java/Node/
Python build+test+package, Docker, K8s/Cloud Run deploy) if no
directory is given, so the tool is immediately usable out of the box.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from langchain_core.documents import Document

DEFAULT_BLOCKS_DIR = Path(__file__).resolve().parent / "example_blocks"


def _parse_block_file(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    _, frontmatter_str, content = raw.split("---", 2)
    metadata = yaml.safe_load(frontmatter_str) or {}
    metadata["block_id"] = path.stem
    # ci_system defaults to gitlab-ci -- an explicit extension point:
    # a contributor adding GitHub Actions support would tag new blocks
    # ci_system: github-actions and extend validate.py with a matching
    # parser, without touching this loader at all.
    metadata.setdefault("ci_system", "gitlab-ci")

    tag_line = f"Tags: {metadata.get('tags', '')}\n\n"
    return Document(page_content=tag_line + content.strip(), metadata=metadata)


def load_all_blocks(blocks_dir: str | Path | None = None) -> list[Document]:
    directory = Path(blocks_dir) if blocks_dir else DEFAULT_BLOCKS_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"Blocks directory not found: {directory}")

    block_files = sorted(directory.glob("*.block"))
    if not block_files:
        raise ValueError(f"No .block files found in {directory}")

    return [_parse_block_file(p) for p in block_files]


if __name__ == "__main__":
    blocks = load_all_blocks()
    print(f"Loaded {len(blocks)} blocks from {DEFAULT_BLOCKS_DIR}")
    for b in blocks:
        print(f"  [{b.metadata['block_id']}] stage_type={b.metadata.get('stage_type')} "
              f"tags={b.metadata.get('tags')}")
