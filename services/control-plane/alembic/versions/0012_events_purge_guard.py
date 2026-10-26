"""agent_events stays append-only; retention may DELETE only inside a purge transaction.

The purge job runs `SET LOCAL aihub.purge = 'on'`, which lasts until its transaction ends.
UPDATE is always rejected, and nothing needs DDL (no DISABLE TRIGGER, no table lock).
"""

from alembic import op

revision = "0012_events_purge_guard"
down_revision = "0011_attachments_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION control.reject_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('aihub.purge', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'agent_events is append-only';
        END; $$
        """
    )


def downgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION control.reject_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'agent_events is append-only'; END; $$"
    )
