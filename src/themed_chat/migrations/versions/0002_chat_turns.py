import sqlalchemy as sa
from alembic import op

revision = "0002_chat_turns"
down_revision = "0001_users"


def upgrade() -> None:
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("question_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_turns")
