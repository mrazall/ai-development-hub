"""${message}"""
from alembic import op
import sqlalchemy as sa
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
def upgrade(): pass
def downgrade(): pass
