"""Add exclusion constraint to prevent overlapping doctor working hours.

Revision ID: 0002_working_hours_overlap
Revises: 0001_initial_schema
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_working_hours_overlap"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ex_doctor_working_hours_no_overlap"


def _constraint_exists() -> bool:
    exists = op.get_bind().scalar(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = :constraint_name
            )
            """
        ),
        {"constraint_name": CONSTRAINT_NAME},
    )
    return bool(exists)


def upgrade() -> None:
    # 0001 create_all() already adds this constraint from current models.
    # Inspect pg_constraint first; do not attempt DDL that would abort the
    # migration transaction if the constraint is already present.
    if _constraint_exists():
        return
    op.execute(
        sa.text(
            """
            ALTER TABLE doctor_working_hours
            ADD CONSTRAINT ex_doctor_working_hours_no_overlap
            EXCLUDE USING gist (
                doctor_id WITH =,
                day_of_week WITH =,
                tsrange(
                    (DATE '2000-01-01' + start_time),
                    (DATE '2000-01-01' + end_time),
                    '[)'
                ) WITH &&
            )
            """
        )
    )


def downgrade() -> None:
    # 0001 owns this constraint on a fresh database. Do not drop it.
    return
