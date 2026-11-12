"""Re-embed every memory with the current embedding provider.

Run after switching EMBEDDING_PROVIDER (./kin.sh set-openai-key does this).
Uses the admin URL because it touches every person's rows; it only rewrites
the derived `embedding` / `embedding_model` columns, never the text.
"""

import asyncio
import sys

import asyncpg

from app.config import get_settings
from app.db.migrate import _plain_url
from app.providers.embeddings import build_embeddings
from app.services.memory import vector_literal

BATCH = 64


async def main() -> int:
    s = get_settings()
    if not s.database_admin_url:
        print("DATABASE_ADMIN_URL is required", file=sys.stderr)
        return 2
    emb = build_embeddings(s)
    conn = await asyncpg.connect(_plain_url(s.database_admin_url))
    done = 0
    try:
        while True:
            rows = await conn.fetch(
                "select id, content from public.memories where embedding_model is distinct from $1 limit $2",
                emb.model_name,
                BATCH,
            )
            if not rows:
                break
            vecs = await emb.embed([r["content"] for r in rows])
            for r, v in zip(rows, vecs, strict=True):
                await conn.execute(
                    "update public.memories set embedding = $1::extensions.vector, embedding_model = $2 where id = $3",
                    vector_literal(v),
                    emb.model_name,
                    r["id"],
                )
            done += len(rows)
            print(f"re-embedded {done}")
    finally:
        await conn.close()
    print(f"done: {done} memories now use {emb.model_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
