"""cascade delete on listening_history and payments



Revision ID: 002_cascade_listening_payment

Revises: 001_cascade_delete

Create Date: 2026-06-02

"""

from typing import Sequence, Union



from alembic import op

import sqlalchemy as sa





revision: str = "002_cascade_listening_payment"

down_revision: Union[str, None] = "001_cascade_delete"

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None





def _table_exists(name: str) -> bool:

    bind = op.get_bind()

    return name in sa.inspect(bind).get_table_names()





def _recreate_fk(table, constraint, ref_table, columns, ref_columns):

    if not _table_exists(table):

        return

    op.drop_constraint(constraint, table, type_="foreignkey")

    op.create_foreign_key(

        constraint, table, ref_table, columns, ref_columns, ondelete="CASCADE"

    )





def upgrade() -> None:

    _recreate_fk("listening_history", "listening_history_user_id_fkey", "users", ["user_id"], ["id"])

    _recreate_fk("listening_history", "listening_history_track_id_fkey", "tracks", ["track_id"], ["id"])

    _recreate_fk("payments", "payments_user_id_fkey", "users", ["user_id"], ["id"])





def downgrade() -> None:

    def _revert_fk(table, constraint, ref_table, columns, ref_columns):

        if not _table_exists(table):

            return

        op.drop_constraint(constraint, table, type_="foreignkey")

        op.create_foreign_key(constraint, table, ref_table, columns, ref_columns)



    _revert_fk("payments", "payments_user_id_fkey", "users", ["user_id"], ["id"])

    _revert_fk("listening_history", "listening_history_track_id_fkey", "tracks", ["track_id"], ["id"])

    _revert_fk("listening_history", "listening_history_user_id_fkey", "users", ["user_id"], ["id"])

