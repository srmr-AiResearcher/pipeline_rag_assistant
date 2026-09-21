"""
Validation — the safety net this use case needs that the FAQ project
never did. A wrong FAQ answer is a wrong sentence; a broken pipeline
YAML is something that fails at CI runtime, possibly after a delay,
in a way that's confusing to debug. Catch syntax problems HERE,
before the person ever copies this into a real repo.

This does NOT check semantic correctness (is the deploy target right,
are the stages in a sensible order) -- only that it's syntactically
valid YAML. That's a real, honest limitation: a pipeline can parse
fine and still be wrong. Deeper validation (dry-running against a
real GitLab instance, or a schema check against GitLab's CI syntax
specifically) would be the natural next step, not built here.
"""

from __future__ import annotations

import re

import yaml


class _DuplicateKeyError(yaml.YAMLError):
    pass


class _StrictLoader(yaml.SafeLoader):
    """Standard yaml.safe_load() silently keeps only the LAST occurrence
    of a duplicate mapping key, discarding the first entirely -- this is
    valid per the YAML spec, but it's exactly how a real bug slipped
    through undetected: an LLM emitting `deploy_k8s:` twice (once
    correct, once with a line missing) silently loses the correct
    version, with no error anywhere. This loader raises instead of
    silently overwriting, so that specific failure mode is now caught."""


def _construct_mapping_no_duplicates(loader: yaml.SafeLoader, node, deep: bool = False) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise _DuplicateKeyError(
                f"Duplicate key {key!r} found -- YAML would normally silently keep only "
                f"the LAST occurrence and discard the first. This is a common, dangerous "
                f"LLM output error (e.g. two 'deploy:' jobs where the second overwrites "
                f"the first's actual deploy command with an incomplete version)."
            )
        value = loader.construct_object(value_node, deep=deep)
        mapping[key] = value
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


def extract_yaml_block(model_output: str) -> str | None:
    """LLM responses typically wrap code in markdown fences. Pull out
    the largest ```yaml ... ``` or ``` ... ``` block, since that's
    almost certainly the actual pipeline, not the explanatory prose
    around it."""
    fenced_blocks = re.findall(r"```(?:yaml|yml)?\n(.*?)```", model_output, re.DOTALL)
    if not fenced_blocks:
        return None
    return max(fenced_blocks, key=len)


def validate_pipeline_yaml(model_output: str) -> dict:
    yaml_text = extract_yaml_block(model_output)
    if yaml_text is None:
        return {"valid": False, "error": "No fenced YAML block found in model output", "parsed": None}

    try:
        parsed = yaml.load(yaml_text, Loader=_StrictLoader)
    except _DuplicateKeyError as e:
        return {"valid": False, "error": str(e), "parsed": None}
    except yaml.YAMLError as e:
        return {"valid": False, "error": str(e), "parsed": None}

    if not isinstance(parsed, dict):
        return {"valid": False, "error": "Parsed YAML is not a mapping (unexpected top-level type)", "parsed": None}

    missing = []
    if "stages" not in parsed:
        missing.append("stages")
    if missing:
        return {"valid": False, "error": f"Missing expected top-level key(s): {missing}", "parsed": parsed}

    return {"valid": True, "error": None, "parsed": parsed}
