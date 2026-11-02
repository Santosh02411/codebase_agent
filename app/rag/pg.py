"""PostgreSQL + pgvector store: repositories, files (parsed facts), chunks (text + metadata + BM25 term frequencies),
and one vector table per embedding model (HNSW index), so several models can live side by side for comparison.

Keyword search is real Okapi BM25 computed in SQL from per-chunk term frequencies, using the same formula and tokenizer as the
in-memory index (parity is tested). Vector search is cosine distance with pgvector. Indexing is incremental: only changed files'
chunks are rewritten, identical chunk text keeps its vector, and embedding is resumable (chunks without a vector are picked
up by the next run)."""
from __future__ import annotations
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from ..intel.model import FileFacts
from ..parsing.chunker import Chunk
from ..retrieval.bm25 import B, K1, bm25_idf, query_terms
from ..retrieval.index import CodeIndex
from ..utils import tokenize
from .textutil import chunk_tokens, content_hash, embed_text

MAX_HNSW_DIM = 2000          # pgvector's HNSW limit for `vector`; larger models are searched exactly (or use fewer dimensions)
EXACT_SCAN_MAX = 30_000      # repos up to this many chunks use an exact scan: always correct, and fast at this size
Progress = Callable[[str, int, int], None]

MIGRATIONS: list[tuple[int, str]] = [(1, """
CREATE TABLE repositories (
    id text PRIMARY KEY, name text NOT NULL, source text NOT NULL, meta jsonb NOT NULL DEFAULT '{}',
    tree text[] NOT NULL DEFAULT '{}', deps jsonb NOT NULL DEFAULT '{}', imports jsonb NOT NULL DEFAULT '{}',
    context jsonb NOT NULL DEFAULT '{}', extractor_version int NOT NULL DEFAULT 0,
    n_chunks int NOT NULL DEFAULT 0, avgdl double precision NOT NULL DEFAULT 1, indexed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE files (
    repo_id text NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, path text NOT NULL, language text NOT NULL,
    hash text NOT NULL, lines int NOT NULL, facts jsonb NOT NULL, PRIMARY KEY (repo_id, path)
);
CREATE TABLE chunks (
    id bigserial PRIMARY KEY, repo_id text NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    file_path text NOT NULL, ord int NOT NULL, kind text NOT NULL, name text NOT NULL, qualname text NOT NULL,
    start_line int NOT NULL, end_line int NOT NULL, language text NOT NULL, route text NOT NULL DEFAULT '',
    symbol_id text NOT NULL DEFAULT '', signature text NOT NULL DEFAULT '', doc text NOT NULL DEFAULT '',
    calls text[] NOT NULL DEFAULT '{}', text text NOT NULL, content_hash text NOT NULL,
    tf jsonb NOT NULL, doc_len int NOT NULL, fts tsvector NOT NULL
);
CREATE INDEX chunks_repo_file ON chunks (repo_id, file_path, ord);
CREATE INDEX chunks_repo_hash ON chunks (repo_id, content_hash);
CREATE INDEX chunks_fts ON chunks USING gin (fts);
CREATE TABLE term_stats (repo_id text NOT NULL REFERENCES repositories(id) ON DELETE CASCADE, term text NOT NULL, df int NOT NULL, PRIMARY KEY (repo_id, term));
CREATE TABLE embedding_models (key text PRIMARY KEY, name text NOT NULL, dim int NOT NULL, table_name text NOT NULL, ann boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
""")]


def _as_array(v) -> np.ndarray:
    """pgvector returns numpy arrays or `Vector` objects depending on the package version."""
    return np.asarray(v.to_numpy() if hasattr(v, "to_numpy") else v, dtype=np.float32)


def lexeme_literal(terms) -> str:
    """tsvector literal that bypasses PostgreSQL's text parser: our tokenizer already decided what a term is."""
    return " ".join("'" + t.replace("\\", "\\\\").replace("'", "''") + "'" for t in terms)


def model_table(name: str, dim: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:28]
    return f"emb_{slug}_{dim}_{hashlib.sha1(f'{name}|{dim}'.encode()).hexdigest()[:6]}"


@dataclass
class SyncReport:
    chunks_total: int = 0
    chunks_inserted: int = 0
    chunks_deleted: int = 0
    vectors_reused: int = 0
    vectors_embedded: int = 0
    vectors_pending: int = 0
    files_rewritten: int = 0
    ms: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class PgStore:
    def __init__(self, dsn: str, schema: str | None = None, pool_size: int = 8) -> None:
        self.dsn, self.schema = dsn, schema
        options = f"-c search_path={schema},public" if schema else None
        kwargs = {"autocommit": True}
        if options:
            kwargs["options"] = options
        with psycopg.connect(dsn, **kwargs) as c:    # extension + schema must exist before the pool registers the vector type
            c.execute("CREATE EXTENSION IF NOT EXISTS vector")
            if schema:
                c.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            self._migrate(c)
        self.pool = ConnectionPool(dsn, min_size=1, max_size=pool_size, kwargs={"autocommit": False, **({"options": options} if options else {})},
                                   configure=register_vector, open=False)
        self.pool.open(wait=True, timeout=30)
        self._models: dict[str, tuple[str, int]] = {}

    def close(self) -> None:
        self.pool.close()

    @staticmethod
    def _migrate(conn) -> None:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(727274)")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version int PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for version, ddl in MIGRATIONS:
                if version not in done:
                    conn.execute(ddl)
                    conn.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))

    # ---- repositories -----------------------------------------------------------------------------
    def put_repo(self, repo_id: str, name: str, source: str, meta: dict) -> None:
        with self.pool.connection() as c:
            c.execute("""INSERT INTO repositories(id, name, source, meta) VALUES (%s, %s, %s, %s)
                         ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, source = EXCLUDED.source, meta = EXCLUDED.meta""",
                      (repo_id, name, source, Jsonb(meta)))

    def get_repo(self, repo_id: str) -> dict | None:
        with self.pool.connection() as c:
            r = c.execute("SELECT meta FROM repositories WHERE id = %s AND meta <> '{}'::jsonb", (repo_id,)).fetchone()
        return r[0] if r else None

    def list_repos(self) -> list[dict]:
        with self.pool.connection() as c:
            # a row whose meta is still empty is an import that hasn't finished its first index: not listed yet
            return [r[0] for r in c.execute("SELECT meta FROM repositories WHERE meta <> '{}'::jsonb ORDER BY indexed_at DESC")]

    def delete_repo(self, repo_id: str) -> None:
        with self.pool.connection() as c:
            c.execute("DELETE FROM repositories WHERE id = %s", (repo_id,))

    def load_facts(self, repo_id: str, extractor_version: int) -> dict[str, dict]:
        """Previously parsed files (path -> facts dict with its content hash) for incremental indexing."""
        with self.pool.connection() as c:
            v = c.execute("SELECT extractor_version FROM repositories WHERE id = %s", (repo_id,)).fetchone()
            if not v or v[0] != extractor_version:
                return {}
            return {p: f for p, f in c.execute("SELECT path, facts FROM files WHERE repo_id = %s", (repo_id,))}

    # ---- embedding tables ---------------------------------------------------------------------------
    def ensure_model(self, embedder) -> tuple[str, int]:
        """(table name, dim) for an embedder, creating the vector table + HNSW index on first use."""
        name = embedder.name
        if name in self._models:
            return self._models[name]
        dim = int(embedder.dim or 0) or int(len(embedder.embed_query("dimension probe")))
        table = model_table(name, dim)
        with self.pool.connection() as c:
            row = c.execute("SELECT table_name, dim FROM embedding_models WHERE key = %s", (name,)).fetchone()
            if row:
                if row[1] != dim:
                    raise ValueError(f"embedding model {name!r} is stored with {row[1]} dimensions but now produces {dim}")
                self._models[name] = (row[0], row[1])
                return self._models[name]
            ann = dim <= MAX_HNSW_DIM
            t = sql.Identifier(table)
            c.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {t} (chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                                 repo_id text NOT NULL, content_hash text NOT NULL, embedding vector({dim}) NOT NULL)""").format(t=t, dim=sql.SQL(str(dim))))
            c.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {i} ON {t} (repo_id, content_hash)").format(i=sql.Identifier(f"{table}_repo_hash"), t=t))
            if ann:
                c.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {i} ON {t} USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)")
                          .format(i=sql.Identifier(f"{table}_hnsw"), t=t))
            c.execute("INSERT INTO embedding_models(key, name, dim, table_name, ann) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING",
                      (name, name, dim, table, ann))
        self._models[name] = (table, dim)
        return table, dim

    def models(self) -> list[dict]:
        with self.pool.connection() as c:
            rows = c.execute("SELECT key, dim, table_name, ann FROM embedding_models ORDER BY created_at").fetchall()
            out = []
            for key, dim, table, ann in rows:
                n = c.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
                out.append({"model": key, "dim": dim, "table": table, "hnsw": ann, "vectors": n})
        return out

    # ---- indexing -------------------------------------------------------------------------------------
    def sync_repository(self, repo_id: str, *, name: str, source: str, meta: dict, facts: dict[str, FileFacts], chunks: list[Chunk],
                        changed: set[str], tree: list[str], deps: dict, imports: dict, context: dict, extractor_version: int,
                        embedder, progress: Progress | None = None) -> SyncReport:
        """Make the database match the freshly parsed repository, touching only what changed."""
        t0 = time.time()
        progress = progress or (lambda *_: None)
        rep = SyncReport(chunks_total=len(chunks))
        table, _ = self.ensure_model(embedder)
        by_file: dict[str, list[Chunk]] = {}
        for c in chunks:
            by_file.setdefault(c.file, []).append(c)

        with self.pool.connection() as conn:
            conn.execute("""INSERT INTO repositories(id, name, source, meta) VALUES (%s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, source = EXCLUDED.source""", (repo_id, name, source, Jsonb(meta)))
            conn.commit()
            db_files = {r[0]: r[1] for r in conn.execute("SELECT path, hash FROM files WHERE repo_id = %s", (repo_id,))}
            removed = set(db_files) - set(facts)
            rewrite = set(changed) | removed | {p for p, h in ((p, facts[p].hash) for p in facts) if db_files.get(p) != h}
            rewrite &= set(db_files) | set(facts)
            # vectors we can keep: identical chunk text found anywhere in this repo for this model
            new_hashes = {content_hash(c): c for p in rewrite for c in by_file.get(p, [])}
            keep: dict[str, np.ndarray] = {}
            if new_hashes:
                for h, v in conn.execute(sql.SQL("SELECT DISTINCT ON (content_hash) content_hash, embedding FROM {} WHERE repo_id = %s AND content_hash = ANY(%s)")
                                         .format(sql.Identifier(table)), (repo_id, list(new_hashes))):
                    keep[h] = _as_array(v)
            progress("writing", 0, len(rewrite))
            with conn.transaction():
                if rewrite:
                    rep.chunks_deleted = conn.execute("WITH d AS (DELETE FROM chunks WHERE repo_id = %s AND file_path = ANY(%s) RETURNING 1) SELECT count(*) FROM d",
                                                      (repo_id, list(rewrite))).fetchone()[0]
                    conn.execute("DELETE FROM files WHERE repo_id = %s AND path = ANY(%s)", (repo_id, list(rewrite)))
                new_chunks = [c for p in sorted(rewrite) for c in by_file.get(p, [])]
                ids = [r[0] for r in conn.execute("SELECT nextval(pg_get_serial_sequence('chunks', 'id')) FROM generate_series(1, %s)", (len(new_chunks),))]
                rows, ord_in_file = [], {}
                for cid, c in zip(ids, new_chunks):
                    ord_in_file[c.file] = ord_in_file.get(c.file, -1) + 1
                    toks = chunk_tokens(c)
                    tf: dict[str, int] = {}
                    for t in toks:
                        tf[t] = tf.get(t, 0) + 1
                    rows.append((cid, repo_id, c.file, ord_in_file[c.file], c.kind, c.name, c.qualname, c.start, c.end, c.language, c.route,
                                 c.symbol_id, c.signature, c.doc, list(c.calls), c.text, content_hash(c), Jsonb(tf), len(toks), lexeme_literal(tf)))
                with conn.cursor() as cur:
                    cur.executemany("""INSERT INTO chunks(id, repo_id, file_path, ord, kind, name, qualname, start_line, end_line, language, route,
                                       symbol_id, signature, doc, calls, text, content_hash, tf, doc_len, fts)
                                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::tsvector)""", rows)
                    cur.executemany("INSERT INTO files(repo_id, path, language, hash, lines, facts) VALUES (%s,%s,%s,%s,%s,%s)",
                                    [(repo_id, p, facts[p].language, facts[p].hash, facts[p].lines, Jsonb(facts[p].to_dict())) for p in sorted(rewrite) if p in facts])
                    reuse = [(cid, repo_id, r[16], keep[r[16]]) for cid, r in zip(ids, rows) if r[16] in keep]
                    cur.executemany(sql.SQL("INSERT INTO {} (chunk_id, repo_id, content_hash, embedding) VALUES (%s,%s,%s,%s)").format(sql.Identifier(table)), reuse)
                rep.chunks_inserted, rep.vectors_reused, rep.files_rewritten = len(new_chunks), len(reuse), len(rewrite)
                conn.execute("DELETE FROM term_stats WHERE repo_id = %s", (repo_id,))
                conn.execute("""INSERT INTO term_stats(repo_id, term, df) SELECT %s, k, count(*) FROM chunks c, jsonb_object_keys(c.tf) AS k
                                WHERE c.repo_id = %s GROUP BY k""", (repo_id, repo_id))
                conn.execute("""UPDATE repositories SET tree = %s, deps = %s, imports = %s, context = %s, extractor_version = %s, indexed_at = now(),
                                n_chunks = (SELECT count(*) FROM chunks WHERE repo_id = %s),
                                avgdl = COALESCE((SELECT avg(doc_len) FROM chunks WHERE repo_id = %s), 1) WHERE id = %s""",
                             (sorted(tree), Jsonb(deps), Jsonb(imports), Jsonb(context), extractor_version, repo_id, repo_id, repo_id))
        # embedding happens outside the write transaction: it can be slow, and failures leave a consistent, resumable state
        rep.vectors_embedded, rep.vectors_pending = self.ensure_embeddings(repo_id, embedder, progress)
        rep.ms = int((time.time() - t0) * 1000)
        return rep

    def ensure_embeddings(self, repo_id: str, embedder, progress: Progress | None = None, batch: int = 64) -> tuple[int, int]:
        """Embed every chunk of the repo that has no vector yet for this model. Returns (embedded, still_pending).
        Re-running after a failure continues where it stopped; calling it with a new model adds that model to an existing repo."""
        progress = progress or (lambda *_: None)
        table, _ = self.ensure_model(embedder)
        t = sql.Identifier(table)
        with self.pool.connection() as c:
            todo = c.execute(sql.SQL("""SELECT c.id, c.file_path, c.qualname, c.route, c.doc, c.text, c.content_hash FROM chunks c
                             LEFT JOIN {t} e ON e.chunk_id = c.id WHERE c.repo_id = %s AND e.chunk_id IS NULL ORDER BY c.id""").format(t=t), (repo_id,)).fetchall()
            c.commit()
        embedded = 0
        try:
            for i in range(0, len(todo), batch):
                part = todo[i:i + batch]
                progress("embedding", i, len(todo))
                texts = [f"{r[1]}\n{r[2]}\n{r[3]}\n{r[4]}\n{r[5]}" for r in part]
                vecs = embedder.embed_documents(texts)
                with self.pool.connection() as c, c.cursor() as cur:
                    cur.executemany(sql.SQL("INSERT INTO {} (chunk_id, repo_id, content_hash, embedding) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING").format(t),
                                    [(r[0], repo_id, r[6], v) for r, v in zip(part, vecs)])
                    c.commit()
                embedded += len(part)
        except Exception:
            return embedded, len(todo) - embedded
        progress("embedding", len(todo), len(todo))
        return embedded, 0

    # ---- loading --------------------------------------------------------------------------------------
    def load_index(self, repo_id: str, embedder) -> "PgCodeIndex":
        table, _ = self.ensure_model(embedder)
        with self.pool.connection() as c:
            repo = c.execute("SELECT tree, deps, imports, context, n_chunks, avgdl FROM repositories WHERE id = %s", (repo_id,)).fetchone()
            if not repo:
                raise KeyError(repo_id)
            rows = c.execute("""SELECT id, file_path, kind, name, qualname, start_line, end_line, text, language, calls, route, symbol_id, signature, doc
                                FROM chunks WHERE repo_id = %s ORDER BY file_path COLLATE "C", ord""", (repo_id,)).fetchall()
            facts = {p: FileFacts.from_dict(f) for p, f in c.execute("SELECT path, facts FROM files WHERE repo_id = %s ORDER BY path COLLATE \"C\"", (repo_id,))}
            pending = c.execute(sql.SQL("SELECT count(*) FROM chunks c LEFT JOIN {} e ON e.chunk_id = c.id WHERE c.repo_id = %s AND e.chunk_id IS NULL")
                                .format(sql.Identifier(table)), (repo_id,)).fetchone()[0]
            c.commit()
        chunks, db_ids = [], []
        for pos, r in enumerate(rows):
            chunks.append(Chunk(pos, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], list(r[9]), r[10], r[11], r[12], r[13]))
            db_ids.append(r[0])
        idx = PgCodeIndex(chunks, list(repo[0]), repo[1], repo[2], embedder, facts, repo[3], store=self, repo_id=repo_id,
                          table=table, db_ids=db_ids, n_chunks=repo[4], avgdl=repo[5])
        idx.pending_vectors = int(pending)
        return idx

    # ---- search legs ----------------------------------------------------------------------------------
    def vector_search(self, repo_id: str, table: str, qvec: np.ndarray, n: int, n_chunks: int) -> list[tuple[int, float]]:
        t = sql.Identifier(table)
        exact = n_chunks <= EXACT_SCAN_MAX
        if exact:   # ties (identical similarity) break by file/position, matching the in-memory index, so results are reproducible
            q = sql.SQL("""SELECT e.chunk_id, 1 - (e.embedding <=> %s) FROM {} e JOIN chunks c ON c.id = e.chunk_id WHERE e.repo_id = %s
                           ORDER BY e.embedding <=> %s, c.file_path COLLATE "C", c.ord LIMIT %s""").format(t)
        else:       # the ANN index can only serve a plain distance ordering
            q = sql.SQL("SELECT chunk_id, 1 - (embedding <=> %s) FROM {} WHERE repo_id = %s ORDER BY embedding <=> %s LIMIT %s").format(t)
        with self.pool.connection() as c:
            with c.transaction():
                if exact:
                    c.execute("SET LOCAL enable_indexscan = off")     # exact nearest neighbours: the planner would otherwise filter an ANN result by repo
                    c.execute("SET LOCAL enable_bitmapscan = off")
                else:
                    c.execute(sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.SQL(str(min(1000, max(100, n * 4))))))
                    try:
                        with c.transaction():
                            c.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")   # pgvector >= 0.8: keeps scanning until the repo filter is satisfied
                    except psycopg.Error:
                        pass
                return [(int(i), float(s)) for i, s in c.execute(q, (qvec, repo_id, qvec, n)).fetchall()]

    def keyword_search(self, repo_id: str, query: str, n: int, n_chunks: int, avgdl: float) -> list[tuple[int, float]]:
        toks = tokenize(query)
        if not toks:
            return []
        with self.pool.connection() as c:
            df = dict(c.execute("SELECT term, df FROM term_stats WHERE repo_id = %s AND term = ANY(%s)", (repo_id, list(set(toks)))).fetchall())
            terms = query_terms(toks, lambda t: bm25_idf(n_chunks, df[t]) if t in df else None)
            if not terms:
                c.commit()
                return []
            rows = c.execute("""
                SELECT c.id, SUM(q.idf * t.tf * (%(k1)s + 1) / (t.tf + %(k1)s * (1 - %(b)s + %(b)s * c.doc_len / %(avg)s))) AS score
                FROM chunks c
                CROSS JOIN LATERAL unnest(%(terms)s::text[], %(idfs)s::float8[]) AS q(term, idf)
                CROSS JOIN LATERAL (SELECT COALESCE((c.tf ->> q.term)::float8, 0) AS tf) t
                WHERE c.repo_id = %(repo)s AND c.fts @@ %(tsq)s::tsquery AND t.tf > 0
                GROUP BY c.id
                ORDER BY score DESC, c.file_path COLLATE "C", c.ord
                LIMIT %(n)s""", {"k1": K1, "b": B, "avg": avgdl, "terms": [t for t, _ in terms], "idfs": [i for _, i in terms],
                                 "repo": repo_id, "tsq": " | ".join("'" + t.replace("'", "''") + "'" for t, _ in terms), "n": n}).fetchall()
            c.commit()
        return [(int(i), float(s)) for i, s in rows]


class PgBackend:
    """Search legs served by PostgreSQL. Positions in the loaded chunk list are translated to/from database ids."""

    def __init__(self, index: "PgCodeIndex") -> None:
        self.ix = index
        self.pos = {d: p for p, d in enumerate(index.db_ids)}

    def vector(self, qvec, n):
        ix = self.ix
        return [(self.pos[i], s) for i, s in ix.store.vector_search(ix.repo_id, ix.table, qvec, n, ix.n_chunks) if i in self.pos]

    def keyword(self, query, n):
        ix = self.ix
        return [(self.pos[i], s) for i, s in ix.store.keyword_search(ix.repo_id, query, n, ix.n_chunks, ix.avgdl) if i in self.pos]


class PgCodeIndex(CodeIndex):
    """CodeIndex whose vectors and keyword statistics live in PostgreSQL. Chunk text/metadata and the code graph are held in
    memory for context building and graph queries (loaded from the database; they are small next to the vectors)."""

    def __init__(self, chunks, tree, deps, imports, embedder, facts, context, *, store: PgStore, repo_id: str, table: str,
                 db_ids: list[int], n_chunks: int, avgdl: float) -> None:
        super().__init__(chunks, None, tree, deps, imports, embedder.name, embedder, facts=facts, context=context, build_bm25=False)
        self.store, self.repo_id, self.table, self.db_ids, self.n_chunks, self.avgdl = store, repo_id, table, db_ids, n_chunks, avgdl
        self.pending_vectors = 0   # chunks that have no vector for this embedding model yet (re-index to embed them)

    def make_backend(self):
        return PgBackend(self)

    def save(self, path) -> None:  # the database is the source of truth; nothing to pickle
        return None
