"""
Smoke tests — deliberately cover only loader.py, validate.py, and
cli.py's argument parsing: none of these need network access, an API
key, or Ollama running. retrieval.py/generate.py need real providers
and are exercised manually (see README), not in this CI-safe suite.

Run: uv run pytest tests/ -v
"""

from __future__ import annotations

import pytest

from pipeline_rag_assistant.cli import build_parser
from pipeline_rag_assistant.loader import DEFAULT_BLOCKS_DIR, load_all_blocks
from pipeline_rag_assistant.validate import extract_yaml_block, validate_pipeline_yaml


def test_bundled_example_blocks_load():
    blocks = load_all_blocks()
    assert len(blocks) == 12
    for b in blocks:
        assert b.page_content.strip() != ""
        assert "block_id" in b.metadata
        assert "ci_system" in b.metadata


def test_every_bundled_block_has_a_stage_type():
    blocks = load_all_blocks()
    stage_types_seen = {b.metadata.get("stage_type") for b in blocks}
    assert stage_types_seen == {"build", "test", "package", "docker", "deploy"}


def test_no_stage_overlap_between_build_and_package():
    """Regression test for the real bug caught earlier in this
    project: build blocks and package blocks both running `mvn
    package` would confuse assembly. Confirm 'package' never appears
    in a build-stage block's script."""
    blocks = load_all_blocks()
    for b in blocks:
        if b.metadata.get("stage_type") == "build" and b.metadata.get("language") == "java":
            assert "package" not in b.page_content, (
                f"{b.metadata['block_id']} is stage_type=build but its script "
                f"runs 'package' -- overlaps with a dedicated package-stage block"
            )


def test_missing_blocks_dir_raises_clear_error(tmp_path):
    nonexistent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        load_all_blocks(nonexistent)


def test_empty_blocks_dir_raises_clear_error(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError):
        load_all_blocks(empty_dir)


def test_extract_yaml_block_finds_fenced_content():
    text = "some prose\n```yaml\nstages:\n  - build\n```\nmore prose"
    result = extract_yaml_block(text)
    assert result is not None
    assert "stages:" in result


def test_extract_yaml_block_returns_none_without_fence():
    assert extract_yaml_block("just plain prose, no code block") is None


def test_validate_pipeline_yaml_passes_on_good_input():
    good = "```yaml\nstages:\n  - build\nbuild:\n  stage: build\n```"
    result = validate_pipeline_yaml(good)
    assert result["valid"] is True


def test_validate_pipeline_yaml_fails_on_broken_syntax():
    broken = "```yaml\nstages: [build\n```"
    result = validate_pipeline_yaml(broken)
    assert result["valid"] is False


def test_validate_pipeline_yaml_fails_when_stages_key_missing():
    no_stages = "```yaml\nbuild:\n  stage: build\n```"
    result = validate_pipeline_yaml(no_stages)
    assert result["valid"] is False
    assert "stages" in result["error"]


def test_cli_ask_parses_expected_arguments():
    parser = build_parser()
    args = parser.parse_args(["ask", "some question", "--llm-provider", "ollama"])
    assert args.command == "ask"
    assert args.question == "some question"
    assert args.llm_provider == "ollama"
    assert args.embed_provider is None  # defaults resolved later, in build_retriever/build_llm


def test_cli_list_blocks_parses_blocks_dir():
    parser = build_parser()
    args = parser.parse_args(["list-blocks", "--blocks-dir", "./my_blocks"])
    assert args.command == "list-blocks"
    assert args.blocks_dir == "./my_blocks"


def test_cli_rejects_unknown_provider():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["ask", "q", "--llm-provider", "not_a_real_provider"])
