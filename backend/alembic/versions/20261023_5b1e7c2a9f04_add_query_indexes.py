"""add query indexes

Indexes for hot read paths: punches by employee + work date (attendance computation),
login logs by user / username, workflow instances by subject user and start time.

Revision ID: 5b1e7c2a9f04
Revises: d823a3f1478f
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5b1e7c2a9f04'
down_revision: Union[str, Sequence[str], None] = 'd823a3f1478f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_attendance_punches_employee_work_date', 'attendance_punches', ['employee_id', 'work_date'],
                    unique=False)
    op.create_index('ix_login_logs_user_id', 'login_logs', ['user_id'], unique=False)
    op.create_index('ix_login_logs_username', 'login_logs', ['username'], unique=False)
    op.create_index('ix_wf_instances_subject_user', 'wf_instances', ['subject_user_id'], unique=False)
    op.create_index('ix_wf_instances_started_at', 'wf_instances', ['started_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_wf_instances_started_at', table_name='wf_instances')
    op.drop_index('ix_wf_instances_subject_user', table_name='wf_instances')
    op.drop_index('ix_login_logs_username', table_name='login_logs')
    op.drop_index('ix_login_logs_user_id', table_name='login_logs')
    op.drop_index('ix_attendance_punches_employee_work_date', table_name='attendance_punches')
