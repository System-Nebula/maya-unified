"""AtomicNote KB tables (kb_atomic_notes, kb_note_edges) with pgvector HNSW."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260712_kb"
down_revision: Union[str, None] = "20260709_music_play_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_atomic_notes (
            id varchar(64) PRIMARY KEY,
            version integer NOT NULL DEFAULT 1,
            title text NOT NULL,
            content text NOT NULL,
            note_type varchar(32) NOT NULL,
            labels jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            valid_start timestamptz,
            valid_end timestamptz,
            source_doc_hash varchar(64),
            page_start integer,
            page_end integer,
            embedding vector(384),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_atomic_notes_note_type "
        "ON kb_atomic_notes (note_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_atomic_notes_source_doc_hash "
        "ON kb_atomic_notes (source_doc_hash)"
    )
    # HNSW needs pgvector >= 0.5; fall back to no ANN index rather than fail.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE INDEX IF NOT EXISTS ix_kb_atomic_notes_embedding_hnsw
                ON kb_atomic_notes USING hnsw (embedding vector_cosine_ops);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'hnsw index unavailable, skipping: %', SQLERRM;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_note_edges (
            src_id varchar(64) NOT NULL
                REFERENCES kb_atomic_notes(id) ON DELETE CASCADE,
            dst_id varchar(64) NOT NULL
                REFERENCES kb_atomic_notes(id) ON DELETE CASCADE,
            predicate varchar(32) NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            weight double precision,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (src_id, dst_id, predicate)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_note_edges_dst_id ON kb_note_edges (dst_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_note_images (
            id varchar(64) PRIMARY KEY,
            note_id varchar(64)
                REFERENCES kb_atomic_notes(id) ON DELETE SET NULL,
            source_doc_hash varchar(64) NOT NULL,
            page_no integer NOT NULL,
            path text NOT NULL,
            width integer NOT NULL,
            height integer NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            embedding vector(512),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_note_images_note_id ON kb_note_images (note_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_note_images_source ON kb_note_images (source_doc_hash)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            CREATE INDEX IF NOT EXISTS ix_kb_note_images_embedding_hnsw
                ON kb_note_images USING hnsw (embedding vector_cosine_ops);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'hnsw index unavailable, skipping: %', SQLERRM;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kb_note_images")
    op.execute("DROP TABLE IF EXISTS kb_note_edges")
    op.execute("DROP TABLE IF EXISTS kb_atomic_notes")
