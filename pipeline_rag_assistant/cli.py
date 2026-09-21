"""
CLI — the actual `pipeline-rag-assistant` command, installed via
`pip install pipeline-rag-assistant` (once published) or `uv run` in
this repo.

Examples:
    pipeline-rag-assistant ask "Build a Spring Boot JAR and deploy to K8s"
    pipeline-rag-assistant ask "..." --blocks-dir ./my_org_blocks
    pipeline-rag-assistant ask "..." --llm-provider openai --embed-provider openai
    pipeline-rag-assistant list-blocks
"""

from __future__ import annotations

import argparse
import sys

from pipeline_rag_assistant.generate import build_chain, build_llm
from pipeline_rag_assistant.loader import load_all_blocks
from pipeline_rag_assistant.retrieval import build_retriever
from pipeline_rag_assistant.validate import validate_pipeline_yaml


def cmd_ask(args: argparse.Namespace) -> int:
    blocks = load_all_blocks(args.blocks_dir)
    retriever = build_retriever(blocks, embed_provider=args.embed_provider)
    llm = build_llm(llm_provider=args.llm_provider, model_name=args.model)
    chain = build_chain(retriever, llm)

    answer = chain.invoke(args.question)
    print(answer)

    result = validate_pipeline_yaml(answer)
    print("\n" + "-" * 60)
    if result["valid"]:
        print(f"[VALIDATION] PASSED -- top-level keys: {list(result['parsed'].keys())}")
        return 0
    else:
        print(f"[VALIDATION] FAILED -- {result['error']}")
        return 1


def cmd_list_blocks(args: argparse.Namespace) -> int:
    blocks = load_all_blocks(args.blocks_dir)
    print(f"{len(blocks)} blocks:")
    for b in blocks:
        print(f"  [{b.metadata['block_id']}] stage_type={b.metadata.get('stage_type')} "
              f"ci_system={b.metadata.get('ci_system')} tags={b.metadata.get('tags')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline-rag-assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--blocks-dir", default=None,
                         help="Path to your own .block files (defaults to bundled examples)")

    ask_parser = subparsers.add_parser("ask", parents=[common])
    ask_parser.add_argument("question")
    ask_parser.add_argument("--embed-provider", default=None, choices=["openai", "huggingface"],
                             help="Env var PIPELINE_RAG_EMBED_PROVIDER also works. Default: huggingface (free/local)")
    ask_parser.add_argument("--llm-provider", default=None, choices=["openai", "gemini", "ollama"],
                             help="Env var PIPELINE_RAG_LLM_PROVIDER also works. Default: ollama (free/local)")
    ask_parser.add_argument("--model", default=None, help="Override the default model name for the chosen provider")
    ask_parser.set_defaults(func=cmd_ask)

    list_parser = subparsers.add_parser("list-blocks", parents=[common])
    list_parser.set_defaults(func=cmd_list_blocks)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
