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

Baseline: `bm25-only`. ▲/▼ = MRR differs from the baseline with p < 0.05 (paired bootstrap over questions). Bold = best in column.
Metric definitions: see app/rag/eval/metrics.py. Context metrics are computed on the token-budgeted context actually given to the LLM.

| embedding model | dim | chunks | index time | API calls | tokens |
|---|---|---|---|---|---|
| hash | 512 | 1277 | 2.09 s | 20 | – |
