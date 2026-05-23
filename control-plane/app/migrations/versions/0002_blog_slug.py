"""Add slug column to blog_posts (idempotent for prod DBs that pre-date init.sql change).

Fresh installs already have the column from init.sql; this revision uses IF NOT EXISTS
guards so re-running on a fresh DB is a no-op.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0002_blog_slug"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add column nullable so existing rows survive.
    op.execute(
        "ALTER TABLE public.blog_posts ADD COLUMN IF NOT EXISTS slug VARCHAR(200)"
    )

    # 2. Backfill slugs from title for any rows where slug IS NULL. Plain SQL
    #    slugify (ASCII-fold via translate, lowercase, dash-collapse). Collision
    #    suffixing handled in a PL/pgSQL block.
    op.execute(
        r"""
        DO $$
        DECLARE
            row RECORD;
            base_slug TEXT;
            candidate TEXT;
            counter INT;
        BEGIN
            FOR row IN SELECT id, title FROM public.blog_posts WHERE slug IS NULL LOOP
                -- slugify: lowercase, drop non-alnum, collapse dashes, trim, fallback
                base_slug := lower(regexp_replace(coalesce(row.title, ''), '[^a-zA-Z0-9]+', '-', 'g'));
                base_slug := trim(both '-' from base_slug);
                base_slug := substring(base_slug from 1 for 180);
                IF base_slug = '' THEN
                    base_slug := 'post';
                END IF;

                candidate := base_slug;
                counter := 2;
                WHILE EXISTS (SELECT 1 FROM public.blog_posts WHERE slug = candidate) LOOP
                    candidate := substring(base_slug from 1 for 180 - length('-' || counter::text)) || '-' || counter::text;
                    counter := counter + 1;
                END LOOP;

                UPDATE public.blog_posts SET slug = candidate WHERE id = row.id;
            END LOOP;
        END$$;
        """
    )

    # 3. Lock down: NOT NULL + unique index.
    op.execute("ALTER TABLE public.blog_posts ALTER COLUMN slug SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_blog_posts_slug ON public.blog_posts USING btree (slug)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_blog_posts_slug")
    op.execute("ALTER TABLE public.blog_posts DROP COLUMN IF EXISTS slug")
