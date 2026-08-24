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


def upgrade() -> None:
    # 0001 uses create_all() against current models, which already create this
    # exclusion constraint. Skip if it exists so a fresh production database
    # can reach head without a duplicate-constraint error.
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
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
                );
            EXCEPTION
                WHEN duplicate_object THEN
                    NULL;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE doctor_working_hours DROP CONSTRAINT IF EXISTS ex_doctor_working_hours_no_overlap"
    ))
