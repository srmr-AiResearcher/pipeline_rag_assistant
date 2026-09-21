"""
Generation — same assembly-only prompting as every version of this
project (combine verified blocks, never invent new YAML). Generalized
to support THREE providers, so this tool works whether you have a
paid API key or not:

  - "openai"     : ChatOpenAI, needs OPENAI_API_KEY
  - "gemini"     : ChatGoogleGenerativeAI, needs GCP auth + project
  - "ollama"     : ChatOllama, fully free/local -- needs Ollama
                    installed and a model pulled (e.g. `ollama pull
                    llama3.2`), no API key or network call at all

*** Known provider-specific gotcha: GPT-5 models only accept
temperature=1 or unset -- passing temperature=0 errors. This function
does not pass temperature for the openai branch for that reason. ***
"""

from __future__ import annotations

import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

ASSEMBLY_PROMPT = """You are assembling a {ci_system} pipeline from PRE-WRITTEN, \
VERIFIED pipeline blocks below. Do not invent new stages or write new YAML \
from scratch -- only combine, lightly adapt, and explain the blocks given.

AVAILABLE BLOCKS:
{context}

USER REQUEST:
{question}

INSTRUCTIONS:
1. Select which of the blocks above are actually relevant to the request.
2. Combine them into ONE complete pipeline file, including a stage-order
   list covering every stage you used.
3. If the available blocks are MISSING a stage type or target the request
   clearly needs, say so explicitly -- do not invent a replacement.
4. Briefly note which block_id(s) you used for each stage.

STRICT OUTPUT RULES -- follow these exactly, they are not optional:
- Output EXACTLY ONE fenced YAML code block. Do not present a second
  version, a revised attempt, or an alternative approach after it,
  even if you think of a way to improve your first answer -- decide
  BEFORE writing the code block, not after.
- Every stage/job name (the top-level YAML key) must appear ONLY ONCE
  in the file. Never define the same job twice, even if you want to
  show two versions of it -- pick one and use it.
- If you are unsure which blocks to include, say so in your explanation
  BEFORE the code block, then still output only one final YAML block.
"""


def build_llm(llm_provider: str | None = None, model_name: str | None = None):
    llm_provider = llm_provider or os.environ.get("PIPELINE_RAG_LLM_PROVIDER", "ollama")

    if llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name or "gpt-5.4")

    if llm_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ValueError("Set GOOGLE_CLOUD_PROJECT for the gemini provider.")
        return ChatGoogleGenerativeAI(
            model=model_name or "gemini-2.5-flash", project=project, location="us-central1"
        )

    if llm_provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model_name or "llama3.2")

    raise ValueError(f"Unknown llm provider: {llm_provider!r} (expected 'openai', 'gemini', or 'ollama')")


def build_chain(retriever, llm):
    prompt = ChatPromptTemplate.from_template(ASSEMBLY_PROMPT)

    def format_blocks(docs) -> str:
        if not docs:
            return "(no matching blocks found)"
        parts = []
        for d in docs:
            # Strip the "Tags: ...\n\n" line loader.py prepends for BM25
            # matching only -- it's retrieval metadata, not real pipeline
            # config. Leaving it in caused the model to literally copy
            # it into assembled YAML as GitLab's `tags:` keyword (which
            # selects a RUNNER, a completely unrelated concept) --
            # a real data-leakage bug, not a model mistake.
            content = d.page_content
            if content.startswith("Tags: ") and "\n\n" in content:
                content = content.split("\n\n", 1)[1]
            parts.append(
                f"--- block_id={d.metadata['block_id']} (stage_type={d.metadata.get('stage_type')}) ---\n{content}"
            )
        return "\n\n".join(parts)

    def build_inputs(question: str) -> dict:
        docs = retriever.invoke(question)
        ci_system = docs[0].metadata.get("ci_system", "gitlab-ci") if docs else "gitlab-ci"
        return {"context": format_blocks(docs), "question": question, "ci_system": ci_system}

    return build_inputs | prompt | llm | StrOutputParser()
