#!/usr/bin/env python3
"""Fill pgvector embeddings for Wolfy knowledge_chunks.

Default mode remains free/local: deterministic hashed token vectors normalized to
1536 dimensions. When a semantic provider is configured, the same vector(1536)
contract is filled with true embeddings and provider/model metadata is recorded
per chunk so old local vectors can be selectively re-embedded.

Configured semantic provider today:
- OpenAI: set OPENAI_API_KEY and optionally WOLFY_EMBEDDING_PROVIDER=openai and
  WOLFY_EMBEDDING_MODEL=text-embedding-3-small. The script requests 1536 dims.

Useful examples:
  python3 embed_knowledge_chunks.py --limit 200 --report
  WOLFY_EMBEDDING_PROVIDER=openai python3 embed_knowledge_chunks.py --reembed-all --limit 50 --report
  python3 embed_knowledge_chunks.py --smoke-test "risk managed swing trading"
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from typing import Iterable

import psycopg
from psycopg.types.json import Jsonb

PG_DSN = os.environ.get('WOLFY_PG_DSN', 'dbname=wolfy user=root host=/var/run/postgresql')
DIMS = 1536
LOCAL_METHOD = 'local_hashing_vector_v1'
SEMANTIC_METHOD = 'semantic_embedding_v1'
DEFAULT_OPENAI_MODEL = 'text-embedding-3-small'
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]{1,}")

SMOKE_TEST_SQL = """
WITH query_vec AS (SELECT %s::vector AS embedding),
vector_rank AS (
    SELECT id, source_table, source_id, left(content, 220) AS snippet,
           1 - (embedding <=> (SELECT embedding FROM query_vec)) AS score
    FROM knowledge_chunks
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> (SELECT embedding FROM query_vec)
    LIMIT %s
),
trigram_rank AS (
    SELECT id, source_table, source_id, left(content, 220) AS snippet,
           similarity(content, %s) AS score
    FROM knowledge_chunks
    WHERE content %% %s OR similarity(content, %s) > 0
    ORDER BY similarity(content, %s) DESC
    LIMIT %s
)
SELECT 'vector' AS retrieval_path, * FROM vector_rank
UNION ALL
SELECT 'trigram' AS retrieval_path, * FROM trigram_rank;
"""


@dataclass(frozen=True)
class EmbeddingProvider:
    provider: str
    model: str
    method: str
    dimensions: int = DIMS

    def embed_one(self, text: str) -> list[float]:
        if self.provider == 'local':
            return local_hash_embed(text)
        if self.provider == 'openai':
            return openai_embed_many([text], self.model, self.dimensions)[0]
        raise ValueError(f'unsupported embedding provider: {self.provider}')

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        if self.provider == 'local':
            return [local_hash_embed(text) for text in texts]
        if self.provider == 'openai':
            return openai_embed_many(texts, self.model, self.dimensions)
        raise ValueError(f'unsupported embedding provider: {self.provider}')


def local_hash_embed(text: str) -> list[float]:
    tokens = [t.lower() for t in TOKEN_RE.findall(text or '')]
    counts = Counter(tokens)
    vec = [0.0] * DIMS
    for tok, count in counts.items():
        digest = hashlib.blake2b(tok.encode(), digest_size=8).digest()
        n = int.from_bytes(digest, 'big')
        idx = n % DIMS
        sign = 1.0 if ((n >> 11) & 1) else -1.0
        # log-scaled term frequency keeps repeated words from dominating.
        vec[idx] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 8) for x in vec]


# Backward-compatible name for any older import/tests.
def embed(text: str) -> list[float]:
    return local_hash_embed(text)


def openai_embed_many(texts: list[str], model: str, dimensions: int) -> list[list[float]]:
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is required for OpenAI semantic embeddings')
    payload: dict[str, object] = {'model': model, 'input': texts}
    # text-embedding-3* supports dimensions; older 1536-dim models ignore/forbid it.
    if model.startswith('text-embedding-3'):
        payload['dimensions'] = dimensions
    req = urllib.request.Request(
        os.environ.get('OPENAI_EMBEDDINGS_URL', 'https://api.openai.com/v1/embeddings'),
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get('WOLFY_EMBEDDING_TIMEOUT', '60'))) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')[:1000]
        raise RuntimeError(f'OpenAI embedding request failed: HTTP {e.code}: {detail}') from e

    data = sorted(body.get('data', []), key=lambda item: item.get('index', 0))
    vectors = [item['embedding'] for item in data]
    if len(vectors) != len(texts):
        raise RuntimeError(f'OpenAI returned {len(vectors)} embeddings for {len(texts)} inputs')
    for i, vec in enumerate(vectors):
        if len(vec) != dimensions:
            raise RuntimeError(f'OpenAI embedding {i} has {len(vec)} dimensions; expected {dimensions}')
    return [[float(x) for x in vec] for vec in vectors]


def resolve_provider(provider: str = 'auto', model: str | None = None, require_semantic: bool = False) -> EmbeddingProvider:
    requested = (provider or os.environ.get('WOLFY_EMBEDDING_PROVIDER') or 'auto').strip().lower()
    configured_model = model or os.environ.get('WOLFY_EMBEDDING_MODEL')

    if requested == 'auto':
        requested = (os.environ.get('WOLFY_EMBEDDING_PROVIDER') or '').strip().lower()
        if not requested:
            requested = 'openai' if os.environ.get('OPENAI_API_KEY') else 'local'

    if requested in {'local', 'hash', 'hashing', LOCAL_METHOD}:
        if require_semantic:
            raise RuntimeError('semantic embeddings required, but only local fallback is configured')
        return EmbeddingProvider(provider='local', model=LOCAL_METHOD, method=LOCAL_METHOD, dimensions=DIMS)

    if requested == 'openai':
        if not os.environ.get('OPENAI_API_KEY'):
            if require_semantic:
                raise RuntimeError('OPENAI_API_KEY is not set; cannot use OpenAI semantic embeddings')
            return EmbeddingProvider(provider='local', model=LOCAL_METHOD, method=LOCAL_METHOD, dimensions=DIMS)
        return EmbeddingProvider(
            provider='openai',
            model=configured_model or DEFAULT_OPENAI_MODEL,
            method=SEMANTIC_METHOD,
            dimensions=DIMS,
        )

    if require_semantic:
        raise RuntimeError(f'unsupported semantic embedding provider: {requested}')
    return EmbeddingProvider(provider='local', model=LOCAL_METHOD, method=LOCAL_METHOD, dimensions=DIMS)


def embedding_metadata(provider: EmbeddingProvider) -> dict[str, object]:
    return {
        'embedding_provider': provider.provider,
        'embedding_model': provider.model,
        'embedding_method': provider.method,
        'embedding_dimensions': provider.dimensions,
    }


def build_selection_filter(provider: EmbeddingProvider, reembed_all: bool = False) -> tuple[str, list[object]]:
    if reembed_all:
        return 'TRUE', []
    return (
        """
        (
            embedding IS NULL
            OR metadata->>'embedding_provider' IS DISTINCT FROM %s
            OR metadata->>'embedding_model' IS DISTINCT FROM %s
            OR metadata->>'embedding_method' IS DISTINCT FROM %s
            OR COALESCE((metadata->>'embedding_dimensions')::integer, 0) <> %s
        )
        """,
        [provider.provider, provider.model, provider.method, provider.dimensions],
    )


def vector_literal(vec: list[float]) -> str:
    if len(vec) != DIMS:
        raise ValueError(f'expected {DIMS}-dimension vector, got {len(vec)}')
    return '[' + ','.join(f'{float(x):.8f}' for x in vec) + ']'


def embed_pending_chunks(provider: EmbeddingProvider, limit: int, reembed_all: bool = False) -> int:
    where_sql, where_params = build_selection_filter(provider, reembed_all=reembed_all)
    processed = 0
    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, content, metadata
            FROM knowledge_chunks
            WHERE {where_sql}
            ORDER BY id
            LIMIT %s
            """,
            (*where_params, limit),
        )
        rows = cur.fetchall()
        vectors = provider.embed_many([content for _, content, _ in rows])
        base_metadata = embedding_metadata(provider)
        for (row_id, _content, metadata), vec in zip(rows, vectors):
            merged_metadata = dict(metadata or {})
            merged_metadata.update(base_metadata)
            cur.execute(
                """
                UPDATE knowledge_chunks
                SET embedding=%s::vector, metadata=%s
                WHERE id=%s
                """,
                (vector_literal(vec), Jsonb(merged_metadata), row_id),
            )
            processed += 1
        conn.commit()
    return processed


def run_smoke_test(provider: EmbeddingProvider, query: str, limit: int = 5) -> list[dict[str, object]]:
    query_vec = vector_literal(provider.embed_one(query))
    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(SMOKE_TEST_SQL, (query_vec, limit, query, query, query, query, limit))
        rows = cur.fetchall()
    keys = ['retrieval_path', 'id', 'source_table', 'source_id', 'snippet', 'score']
    return [dict(zip(keys, row)) for row in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=100)
    ap.add_argument('--provider', default='auto', help='auto, local, or openai; default auto/env')
    ap.add_argument('--model', default=None, help='semantic embedding model; env WOLFY_EMBEDDING_MODEL also works')
    ap.add_argument('--reembed-all', action='store_true', help='replace embeddings even when provider metadata already matches')
    ap.add_argument('--require-semantic', action='store_true', help='fail instead of falling back to local hashes')
    ap.add_argument('--smoke-test', metavar='QUERY', help='compare vector retrieval with trigram retrieval for QUERY')
    ap.add_argument('--report', action='store_true', help='print summary; default is silent unless error')
    args = ap.parse_args()

    provider = resolve_provider(provider=args.provider, model=args.model, require_semantic=args.require_semantic)
    processed = 0
    if args.limit > 0:
        processed = embed_pending_chunks(provider, args.limit, reembed_all=args.reembed_all)

    if args.smoke_test:
        rows = run_smoke_test(provider, args.smoke_test, limit=5)
        print(f'smoke_test_query={args.smoke_test!r} provider={provider.provider} model={provider.model}')
        if not rows:
            print('smoke_test_results=none')
        for row in rows:
            score = row['score']
            if isinstance(score, float):
                score_text = f'{score:.4f}'
            else:
                score_text = str(score)
            snippet = ' '.join(str(row['snippet'] or '').split())
            print(f"{row['retrieval_path']} score={score_text} id={row['id']} source={row['source_table']}:{row['source_id']} :: {snippet}")

    if args.report:
        print(
            'embedded_chunks='
            f'{processed} provider={provider.provider} model={provider.model} '
            f'method={provider.method} dims={provider.dimensions}'
        )


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        raise
