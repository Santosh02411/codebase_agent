## codebase_agent — 50 questions · pgvector · symbol-level labels

| config | MRR | NDCG@10 | R@1 | R@5 | R@10 | P@5 | CtxPrec | CtxRecall | p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25-only | 0.319 | 0.356 | 0.180 | **0.420** | 0.500 | **0.104** | 0.314 | **0.490** | 23.17 |
| hash · vector ▼ | 0.097 | 0.120 | 0.030 | 0.140 | 0.220 | 0.036 | 0.091 | 0.220 | 8.16 |
| hash · hybrid ▼ | 0.189 | 0.236 | 0.080 | 0.270 | 0.420 | 0.064 | 0.172 | 0.340 | 35.41 |
| hash · hybrid + heuristic | **0.339** | **0.379** | **0.190** | **0.420** | **0.540** | 0.100 | **0.331** | 0.480 | 31.39 |

Baseline: `bm25-only`. ▲/▼ = MRR differs from the baseline with p < 0.05 (paired bootstrap over questions). Bold = best in column.
Metric definitions: see app/rag/eval/metrics.py. Context metrics are computed on the token-budgeted context actually given to the LLM.

| embedding model | dim | chunks | index time | API calls | tokens |
|---|---|---|---|---|---|
| hash | 512 | 1277 | 5.34 s | 20 | – |
