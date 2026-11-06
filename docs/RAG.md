# RAG pipeline and retrieval experiments

## Pipeline

```
 import (GitHub / URL / ZIP)                                       question
        │                                                              │
   parse  (Python ast · Tree-sitter ×8)                      embed_query (asymmetric models)
        │                                                              │
   structure-aware chunks (function / class header / module)           ├──► vector search  (pgvector HNSW or exact, cosine)
        │                                                              ├──► BM25 keyword   (SQL or in-memory, identical formula)
   metadata + term frequencies ──► PostgreSQL                          │
   embeddings (OpenAI · Gemini · BGE · hash) ──► pgvector              ▼
                                                           Reciprocal Rank Fusion (weighted)
                                                                       │
                                                           rerank top-N (cross-encoder · heuristic · LLM)
                                                                       │
                                                           context builder: dedupe · per-file cap · token budget · [n] numbering
                                                                       │
                                                           LLM  ──►  answer with [n] citations ──► validated against what was shown
```

| Stage | Code |
|---|---|
| ingestion, incremental indexing | `app/ingest.py`, `app/intel/store.py` |
| parsing, symbols, graphs | `app/intel/` |
| structure-aware chunking | `app/intel/chunks.py` |
| embedding providers | `app/rag/embedders.py` |
| PostgreSQL + pgvector store | `app/rag/pg.py` |
| hybrid retrieval, RRF | `app/rag/retriever.py`, `app/rag/fusion.py`, `app/retrieval/bm25.py` |
| rerankers | `app/rag/rerank.py`, `app/retrieval/reranker.py` |
| context construction, citations | `app/rag/context.py` |
| evaluation | `app/rag/eval/`, `eval/datasets/` |

## PostgreSQL + pgvector

`docker compose up db` (or any PostgreSQL 16 with pgvector) and set `DATABASE_URL`. Tables are created automatically (versioned migrations, advisory-locked).

| Table | Holds |
|---|---|
| `repositories` | registry + metadata, file tree, dependencies, code-graph context, BM25 corpus statistics |
| `files` | per-file content hash and parsed facts (symbols, imports, routes): the incremental-index cache |
| `chunks` | text + metadata (symbol, lines, route, signature, doc) + term frequencies (`tf jsonb`) + `fts tsvector` (GIN) |
| `term_stats` | document frequency per term and repository |
| `embedding_models`, `emb_<model>_<dim>_<hash>` | one vector table per embedding model (HNSW, `vector_cosine_ops`), so several models coexist on the same chunks |

Design decisions worth knowing:

* **Keyword search is real BM25, evaluated in SQL.** Candidates come from the GIN index; each is scored with Okapi BM25 (k1=1.5, b=0.75, Lucene idf) from its stored term frequencies. It uses the same tokenizer and formula as the in-memory index and a test asserts the scores agree to 1e-9. (PostgreSQL's built-in `ts_rank` has no idf, which ranks code poorly, so it is not used.)
* **Incremental and transactional.** Only changed files' chunks are rewritten, in one transaction; identical chunk text keeps its vector; unchanged files keep their chunk ids. A crash mid-write rolls back to the previous index.
* **Embedding is resumable.** Vectors are written outside the write transaction; if the provider fails midway the chunks are already searchable by keyword and the next run embeds only what is missing. `ensure_embeddings(repo, model)` adds a new model to an existing repository without re-parsing.
* **Exact search up to 30 000 chunks, HNSW beyond.** Filtering an ANN result by repository can silently return too few rows, so small and medium repositories use an exact scan (always correct, milliseconds at this size); larger ones use the HNSW index with a larger `ef_search` (and iterative scan on pgvector ≥ 0.8). Exact-scan ties break by file and position, like the in-memory index.
* **Dimensions above 2000** (e.g. OpenAI `text-embedding-3-large` at 3072) exceed pgvector's HNSW limit for `vector`: such models get an exact-scan table. Request fewer dimensions (`:1024`) to keep an ANN index.
* Chunk text and the code graph are loaded into process memory for context building and graph queries; vectors and keyword statistics stay in PostgreSQL.

## Embedding models

Select with `EMBEDDING_PROVIDER`/`EMBEDDING_MODEL`/`EMBEDDING_DIM`, or a spec string in experiments:

| Spec | Notes |
|---|---|
| `hash` | offline feature hashing: lexical, no semantics. The baseline. |
| `openai:text-embedding-3-small[:dim]` | OpenAI `/v1/embeddings`; `OPENAI_BASE_URL` also targets Ollama, vLLM, TEI or LM Studio serving a local model |
| `gemini:gemini-embedding-001[:dim]` | `RETRIEVAL_DOCUMENT` for code, `CODE_RETRIEVAL_QUERY` for questions; truncated dimensions are re-normalised |
| `bge:BAAI/bge-small-en-v1.5` | local, `pip install sentence-transformers`; query instruction applied to queries only (also E5, Nomic prefixes) |
| `fastembed:BAAI/bge-small-en-v1.5` | local ONNX, `pip install fastembed` |

Requests are batched, retried with backoff (honouring `Retry-After`), and API keys never appear in error messages. If the embedding service is down at query time, hybrid search degrades to keyword search and says so in the trace.

## Reranking

`RERANKER=`: `none`, `heuristic` (default: term coverage, symbol/path/route matches, code-over-docs priors), `bge-reranker-base` / `bge-reranker-large` / `cross-encoder:<model>` (needs sentence-transformers; also applies the code-vs-docs priors), or `llm` (listwise scoring by the configured LLM; falls back to the fused order on any error).

## Context and citations

`build_pack` drops chunks that overlap a better-ranked one, caps chunks per file (re-admitted if budget remains), truncates the last chunk that doesn't fit, and numbers what remains `[1]…[n]`. The prompt tells the model to cite with those numbers; `extract_citations` then reports which snippets the answer used and flags numbers that were never shown (`citations.invalid`). The API returns `sources` with `cite` and `cited`; the UI highlights cited sources and warns about invalid ones.

## Evaluation

```bash
python -m app.rag.eval validate --repo . --dataset eval/datasets/codebase_agent.jsonl      # labels point at real files/symbols?
python -m app.rag.eval run --repo . --dataset eval/datasets/codebase_agent.jsonl --preset offline
python -m app.rag.eval run --repo . --dataset eval/datasets/codebase_agent.jsonl \
    --embedders hash,openai:text-embedding-3-small,gemini:gemini-embedding-001,bge:BAAI/bge-small-en-v1.5 \
    --rerankers heuristic,bge-reranker-base                    # every embedder × {vector, hybrid, hybrid + each reranker}
python -m app.rag.eval run ... --store pgvector                # same experiment on PostgreSQL
python -m app.rag.eval generate --repo /path/to/repo -n 100 --out my.jsonl   # synthetic questions with your LLM
```
Models that can't be loaded (missing key or package) are reported as skipped and the rest still run. The same experiments are available from the **Experiments** view in the UI (`/experiments` API).

**Datasets** (`eval/datasets/*.jsonl`): `{"id", "question", "relevant": [{"file", "symbol"?, "lines"?}], "tags"}`. `codebase_agent` has 50 hand-written questions about this repository (about half paraphrase the code instead of naming identifiers; some have two relevant targets); `delivery_sync` has 12 on the tiny test fixture. `.codeagentignore` keeps the datasets out of the index so the benchmark cannot find its own answers.

**Metrics** (`app/rag/eval/metrics.py`; a chunk is relevant if it matches an expected file, and symbol or line range when given):
Recall@K (expected items found in the top K), Precision@K (relevant share of the top K chunks), MRR (1/rank of the first relevant chunk), NDCG@K (binary gain, each expected item counted once), **Context Precision** (RAGAS definition over the chunks actually placed in the LLM context, in order) and **Context Recall** (expected items present in the token-budgeted context). Each is reported at symbol and file level, with 95% bootstrap confidence intervals and paired-bootstrap p-values against a baseline.

### Baseline results (offline, hashing embeddings)

These were produced here with no network access. **They say nothing about OpenAI, Gemini or BGE**, which could not be called from this environment: run the commands above with your keys to fill that comparison in.

## codebase_agent — 50 questions · memory · symbol-level labels

| config | MRR | NDCG@10 | R@1 | R@5 | R@10 | P@5 | CtxPrec | CtxRecall | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25-only | 0.319 | 0.356 | 0.180 | **0.420** | 0.500 | **0.104** | 0.314 | **0.490** | 0.34 |
| hash · vector ▼ | 0.097 | 0.120 | 0.030 | 0.140 | 0.220 | 0.036 | 0.091 | 0.220 | 0.44 |
| hash · hybrid ▼ | 0.189 | 0.236 | 0.080 | 0.270 | 0.420 | 0.064 | 0.172 | 0.340 | 1.26 |
| hash · hybrid + heuristic | **0.339** | **0.379** | **0.190** | **0.420** | **0.540** | 0.100 | **0.331** | 0.480 | 2.14 |


Equal-weight fusion with the weak hashing vectors is *worse* than BM25 alone, and the heuristic reranker recovers it. Sweeping the vector weight and rerank pool:

## codebase_agent — 50 questions · memory · symbol-level labels

| config | MRR | NDCG@10 | R@1 | R@5 | R@10 | P@5 | CtxPrec | CtxRecall | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25-only | 0.319 | 0.356 | 0.180 | 0.420 | 0.500 | 0.104 | 0.314 | 0.490 | 0.35 |
| hybrid wv=0.25 ▼ | 0.240 | 0.294 | 0.110 | 0.360 | 0.510 | 0.092 | 0.224 | 0.420 | 1.06 |
| hybrid wv=0.5 ▼ | 0.219 | 0.263 | 0.120 | 0.280 | 0.440 | 0.072 | 0.208 | 0.380 | 0.93 |
| hybrid wv=1.0 ▼ | 0.189 | 0.236 | 0.080 | 0.270 | 0.420 | 0.064 | 0.172 | 0.340 | 0.73 |
| hybrid+heuristic wv=0.25 pool=10 | 0.346 | 0.377 | **0.220** | 0.440 | 0.510 | 0.104 | 0.342 | 0.490 | 1.25 |
| hybrid+heuristic wv=0.25 pool=30 | **0.360** | **0.400** | 0.200 | **0.460** | **0.580** | **0.108** | **0.350** | 0.530 | 1.89 |
| hybrid+heuristic wv=0.25 pool=50 | 0.357 | 0.398 | 0.200 | **0.460** | **0.580** | **0.108** | 0.349 | **0.550** | 2.71 |
| hybrid+heuristic wv=1.0 pool=10 | 0.291 | 0.317 | 0.190 | 0.350 | 0.420 | 0.084 | 0.286 | 0.400 | 1.26 |
| hybrid+heuristic wv=1.0 pool=30 | 0.339 | 0.379 | 0.190 | 0.420 | 0.540 | 0.100 | 0.331 | 0.480 | 1.95 |
| hybrid+heuristic wv=1.0 pool=50 | 0.338 | 0.384 | 0.190 | 0.420 | 0.560 | 0.100 | 0.330 | 0.500 | 2.62 |
| bm25+heuristic pool=30 | 0.355 | 0.395 | 0.200 | 0.450 | 0.570 | 0.104 | 0.349 | 0.540 | 1.42 |


More weight on the weak vector leg monotonically hurts, and a bigger rerank pool helps. On that evidence the default vector weight is 0.25 for the hashing baseline and 1.0 for real models (`VECTOR_WEIGHT` overrides): re-tune it for your model. The same benchmark through PostgreSQL:

## codebase_agent — 50 questions · pgvector · symbol-level labels

| config | MRR | NDCG@10 | R@1 | R@5 | R@10 | P@5 | CtxPrec | CtxRecall | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25-only | 0.319 | 0.356 | 0.180 | **0.420** | 0.500 | **0.104** | 0.314 | **0.490** | 23.17 |
| hash · vector ▼ | 0.097 | 0.120 | 0.030 | 0.140 | 0.220 | 0.036 | 0.091 | 0.220 | 8.16 |
| hash · hybrid ▼ | 0.189 | 0.236 | 0.080 | 0.270 | 0.420 | 0.064 | 0.172 | 0.340 | 35.41 |
| hash · hybrid + heuristic | **0.339** | **0.379** | **0.190** | **0.420** | **0.540** | 0.100 | **0.331** | 0.480 | 31.39 |


Differences against the in-memory run come from ties in equal similarity scores that numpy-float32 and pgvector round differently; latency is higher because each query is a database round trip.

### Reading the numbers

* 50 questions is small. Confidence intervals are wide and only large gaps are marked ▲/▼; treat unmarked gaps as noise.
* The target repository is this project, so results are tied to a code snapshot and shift as the code changes (`validate` tells you when labels go stale).
* Synthetic questions (`generate`) scale labelling but over-represent self-contained functions and can leak vocabulary (questions containing the symbol name are rejected); use them to compare configurations, not as an absolute score.
