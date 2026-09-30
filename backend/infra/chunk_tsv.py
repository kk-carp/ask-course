"""写入 chunks.content_tsv，供词法召回使用。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.infra.lexical import to_search_text


def update_chunk_content_tsv(session: Session, chunk_id: str, content: str) -> None:
    search_text = to_search_text(content)
    if not search_text:
        return
    session.execute(
        text(
            """
            UPDATE chunks
            SET content_tsv = to_tsvector('simple', :search_text)
            WHERE id = :id
            """
        ),
        {"search_text": search_text, "id": chunk_id},
    )
