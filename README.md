# pipeline-rag-assistant

Retrieve verified CI/CD pipeline template blocks, assemble them into a
complete pipeline via an LLM, and validate the result — **never
free-generate pipeline YAML from scratch.**

Built on the principle that free-form LLM code generation is too
risky for executable infrastructure: this tool retrieves from a
library of *your own, human-verified* pipeline blocks and asks the
LLM to combine and explain them, not invent new ones. If no matching
block exists for what you asked, it says so — it doesn't guess.

## Install

```bash
git clone <this-repo>
cd pipeline-rag-assistant
uv sync
```

## Quickstart

**Step 1 — sanity-check the block library (no network, no LLM, no API key):**
```bash
uv run pipeline-rag-assistant list-blocks
```
You should see 12 blocks listed. If this fails, something's wrong with
the install itself — fix that before going further.

**Step 2 — pick a provider and set it up:**

| Provider | Cost | Setup |
|---|---|---|
| `ollama` (default) | Free, fully local | `ollama pull llama3.2` (one-time) |
| `openai` | Paid, per API call | `export OPENAI_API_KEY=sk-...` |
| `gemini` | Paid, per API call | `gcloud auth application-default login` + `export GOOGLE_CLOUD_PROJECT=...` |

**Step 3 — ask a question:**
```bash
uv run pipeline-rag-assistant ask "Build a Spring Boot JAR and deploy to Kubernetes"
```

**Important:** setting an API key does NOT switch providers by
itself. The default is always `ollama` unless you explicitly say
otherwise — either with a flag:
```bash
uv run pipeline-rag-assistant ask "..." --llm-provider openai
```
or an environment variable, if you don't want to type the flag every time:
```bash
export PIPELINE_RAG_LLM_PROVIDER=openai
uv run pipeline-rag-assistant ask "..."
```
(A real mistake made while building this: setting `OPENAI_API_KEY`
alone and assuming that was enough — it silently kept using Ollama,
producing a confused, lower-quality answer with no error at all. Easy
to miss; check which provider actually ran if a result looks off.)

## Provider reliability — real, observed differences (not hypothetical)

This section reports what actually happened across roughly a dozen
real test runs during development — **a small sample, not a rigorous
benchmark**, but the pattern was consistent enough to be a genuine
signal worth knowing before you rely on this tool with a free/local
model for anything you won't personally review.

**The single most important finding: `llama3.2`'s results were not
stable run-to-run, even asking the exact same question with no
changes at all.** Across repeated attempts at "Build a Spring Boot
JAR and deploy to Kubernetes," the same corpus, same prompt, same
question produced: a fully correct pipeline on some runs, and on
others, one of the distinct failures listed below — never the same
mistake twice, and no way to predict which outcome a given run would
produce in advance. **A single successful test run is not evidence
this model will behave the same way next time.** `gpt-5.4`, by
contrast, produced the same correct structure every time it was tested.

**`llama3.2` (free, local, ~3B parameters) produced a different real
mistake on most attempts, even asking the identical question:**

| Failure observed | What happened | Caught by validation? |
|---|---|---|
| Missing a required stage | Skipped `package` entirely on one run — a JAR was never actually built despite `build` and `deploy` both succeeding | No — valid YAML, just incomplete |
| Duplicate job keys | Defined `deploy_k8s:` twice in one file; YAML's own spec silently keeps only the last one, discarding a working `kubectl set image` command | **Yes**, after we added a custom duplicate-key detector — plain `yaml.safe_load()` does NOT catch this |
| Retrieval metadata leaked into output | Copied our internal `Tags: kubernetes, k8s, ...` line (added only to help keyword search) into the YAML as a bogus `tags:` runner-selector, which would leave the job stuck "pending" forever waiting for a nonexistent Runner | No — fixed at the source instead (stripped before the LLM ever sees it) |
| Declared a block, didn't use it | Said it was using `package_maven_war`, then the final YAML had no package stage at all | No — valid YAML, citation just didn't match content |
| Used a block without declaring it | Silently added a `gcloud run deploy` job (from `deploy_cloudrun`) never mentioned in its own citation list, despite the user only asking for Kubernetes | No — nothing currently checks for this direction |
| Wrong citation | Claimed it used `build_maven_springboot`; the actual script was `gradle compileJava` (a different block's content) | No |
| Multiple draft pipelines in one response | Presented a first attempt, said "this is missing a test stage," then appended a second, revised pipeline — even after the prompt explicitly said not to | Indirectly — this is *why* the duplicate-key case above happened |

**`gpt-5.4` (paid, via OpenAI) has been consistently correct across
every test run performed**, including:
- Every cited `block_id` exactly matching the content actually used, every time.
- Correctly identifying a genuine gap (no container image build/push
  block exists, so the K8s deploy step assumes an image already
  exists elsewhere) — independently, on separate runs, without being
  told to look for that.
- Correctly refusing to invent a deploy target with no matching block
  (asked for Rust + AWS Lambda in a related test with no such block —
  said so plainly instead of guessing).
- Finding a way to include block citations as YAML comments *inside*
  the single output block, satisfying both "cite your sources" and
  "output exactly one code block" instructions at once — a solution
  none of the `llama3.2` runs attempted.

**What this means practically:** if you're using the free/local
default, don't trust a `[VALIDATION] PASSED` message as proof the
pipeline is correct — it only checks YAML syntax and duplicate keys,
neither of which catches "declared a block but didn't use it" or "used
a block without declaring it." Read the actual output, especially the
list of cited `block_id`s, before using it. With a paid provider, the
same advice still applies in principle — just with meaningfully fewer
real failures observed so far.

## Using your own pipeline blocks (the real point of this tool)

```bash
uv run pipeline-rag-assistant ask "..." --blocks-dir ./our_org_blocks
uv run pipeline-rag-assistant list-blocks --blocks-dir ./our_org_blocks
```

Point it at a directory of your own `.block` files — your team's
actual, verified pipeline snippets — and everything else works
unchanged. See `example_blocks/` for the format:

```
---
language: java
build_tool: maven
stage_type: build
tags: java, maven, build, compile
---
build:
  stage: build
  image: maven:3.9-eclipse-temurin-17
  script:
    - mvn clean compile
```

## Using OpenAI or Gemini embeddings too (not just generation)

```bash
uv run pipeline-rag-assistant ask "..." --llm-provider openai --embed-provider openai
```

If you're specifically trying to compare LLM providers (like the
table above), keep `--embed-provider` on the default (`huggingface`,
local) across your tests and only change `--llm-provider` — that way
retrieval stays identical between runs and any difference you observe
is attributable purely to the generator, not a retrieval-side change too.

## Design decisions

- **Blocks are never chunked.** Each `.block` file is one atomic,
  assemblable unit — splitting a pipeline stage risks cutting YAML
  mid-structure.
- **Retrieval favors exact match (70% BM25 / 30% dense).** Stack names
  ("Spring Boot", "Gradle") are exact-match queries wearing
  natural-language clothing, not fuzzy semantic questions.
- **Generation is assembly-only**, never free generation — see the
  prompt in `generate.py`, including explicit rules added after real
  failures (see the provider reliability table above) forbidding
  multiple draft pipelines and duplicate job keys in one response.
- **Post-generation YAML validation** catches syntax errors AND
  duplicate top-level keys (a custom check — plain `yaml.safe_load()`
  silently accepts duplicates and keeps only the last one, discarding
  data). It does NOT check citation honesty (declared-but-missing or
  used-but-undeclared blocks) — a real, currently-open gap, not solved
  here yet.

## Troubleshooting

**`ModuleNotFoundError: No module named 'rank_bm25'` or `'sentence_transformers'`**
Both are real runtime dependencies of LangChain classes used here
(`BM25Retriever`, `HuggingFaceEmbeddings`) that only get imported
*inside* the function that needs them — so a plain install/syntax
check won't catch a missing one. Run `uv sync` again after pulling
the latest `pyproject.toml`; if it still happens, `uv add rank-bm25`
or `uv add sentence-transformers` directly.

**Result looks confused/wrong despite setting an API key**
Check which provider actually ran — setting `OPENAI_API_KEY` or
`GOOGLE_CLOUD_PROJECT` doesn't switch providers by itself; you need
`--llm-provider openai`/`gemini` explicitly, or the matching
`PIPELINE_RAG_LLM_PROVIDER` env var. Default is always `ollama`.

**`[VALIDATION] PASSED` but the pipeline still looks wrong**
See "Provider reliability" above — validation only checks YAML syntax
and duplicate keys, not whether cited blocks were actually used
correctly. Read the output yourself, especially with a free/local model.

## Extending to other CI systems

Every block has a `ci_system` field (defaults to `gitlab-ci`). Adding
GitHub Actions or Jenkins support means: (1) write blocks tagged
`ci_system: github-actions`, (2) extend `validate.py` with a matching
structural check (GitHub Actions YAML doesn't use GitLab's `stages:`/
`stage:` convention). Not implemented here — a genuine open
contribution opportunity.

## Known limitations

- Validation checks YAML syntax and duplicate keys, but not citation
  honesty (see "Provider reliability" above for real examples of both
  failure directions).
- No incremental sync — editing a `.block` file just means re-running.
- Only GitLab CI syntax/conventions are assumed in the assembly prompt.

## CI/CD

This repo ships with two CI configs:
- **`.github/workflows/ci.yml`** — GitHub Actions, runs by default now
  that this repo lives on GitHub. Lint → test → build wheel.
- **`.gitlab-ci.yml`** — kept for reference / in case you mirror this
  repo to GitLab too. Same 3 stages, GitLab syntax.

Neither includes an automatic publish-to-PyPI step — that's a
deliberate one-time decision you'd add yourself, using PyPI's trusted
publishing (OIDC), which works identically well from either GitHub
Actions or GitLab CI/CD — no static API token needed either way.

## License

MIT — see `LICENSE`.
