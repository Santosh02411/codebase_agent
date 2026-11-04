## delivery_sync — 12 questions · memory · symbol-level labels

| config | MRR | NDCG@10 | R@1 | R@5 | R@10 | P@5 | CtxPrec | CtxRecall | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25-only | 0.524 | 0.625 | 0.333 | 0.833 | 0.917 | 0.200 | 0.524 | 0.917 | 0.16 |
| hash · vector | 0.510 | 0.624 | 0.250 | 0.875 | 0.958 | 0.200 | 0.517 | 0.958 | 0.15 |
| hash · hybrid | 0.489 | 0.624 | 0.250 | 0.875 | **1.000** | 0.200 | 0.497 | **1.000** | 0.4 |
| hash · hybrid + heuristic | **0.632** | **0.708** | **0.375** | **0.917** | 0.917 | **0.217** | **0.628** | 0.917 | 0.69 |

Baseline: `bm25-only`. ▲/▼ = MRR differs from the baseline with p < 0.05 (paired bootstrap over questions). Bold = best in column.
Metric definitions: see app/rag/eval/metrics.py. Context metrics are computed on the token-budgeted context actually given to the LLM.

| embedding model | dim | chunks | index time | API calls | tokens |
|---|---|---|---|---|---|
| hash | 512 | 14 | 0.01 s | 1 | – |
