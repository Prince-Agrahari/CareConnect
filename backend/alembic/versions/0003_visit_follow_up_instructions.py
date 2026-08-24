"""Add follow-up instructions on visit notes.

Revision ID: 0003_visit_follow_up
Revises: 0002_working_hours_overlap
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_visit_follow_up"
down_revision: Union[str, None] = "0002_working_hours_overlap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE visit_notes "
            "ADD COLUMN IF NOT EXISTS follow_up_instructions TEXT"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE visit_notes DROP COLUMN IF EXISTS follow_up_instructions"))
