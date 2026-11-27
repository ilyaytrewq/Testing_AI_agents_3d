import sqlalchemy as sa
from alembic import op

revision = "0003_status_sessions"
down_revision = "0002_chat_turns"


def upgrade() -> None:
    op.alter_column("chat_turns", "answer", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "chat_turns",
        sa.Column("status", sa.Text(), nullable=False, server_default="answered"),
    )
    op.create_check_constraint(
        "chat_turns_status_valid",
        "chat_turns",
        "(status = 'answered' AND answer IS NOT NULL) OR (status = 'failed' AND answer IS NULL)",
    )
    op.execute("CREATE SEQUENCE chat_turns_revision_seq AS bigint")
    op.add_column("chat_turns", sa.Column("revision", sa.BigInteger(), nullable=True))
    # Existing turns were written in id order.
    op.execute(
        "UPDATE chat_turns SET revision = numbered.position FROM "
        "(SELECT id, row_number() OVER (ORDER BY id) AS position FROM chat_turns) AS numbered "
        "WHERE chat_turns.id = numbered.id"
    )
    op.execute(
        "SELECT setval('chat_turns_revision_seq', "
        "COALESCE((SELECT max(revision) FROM chat_turns), 0) + 1, false)"
    )
    op.alter_column(
        "chat_turns",
        "revision",
        nullable=False,
        server_default=sa.text("nextval('chat_turns_revision_seq')"),
    )
    op.execute("ALTER SEQUENCE chat_turns_revision_seq OWNED BY chat_turns.revision")
    op.create_index("chat_turns_revision", "chat_turns", ["revision"], unique=True)
    op.create_index("chat_turns_display_order", "chat_turns", ["question_at", "id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "guest_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_index("chat_turns_display_order", "chat_turns")
    op.drop_index("chat_turns_revision", "chat_turns")
    op.drop_column("chat_turns", "revision")
    op.drop_constraint("chat_turns_status_valid", "chat_turns")
    op.drop_column("chat_turns", "status")
    op.execute("DELETE FROM chat_turns WHERE answer IS NULL")
    op.alter_column("chat_turns", "answer", existing_type=sa.Text(), nullable=False)
