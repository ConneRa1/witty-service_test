from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from witty_service.persistence.orm import MessageStatus

revision = "20260520_01"
down_revision = "20260407_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sessions table
    op.add_column("sessions", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("sessions", sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    # messages table
    op.add_column(
        "messages",
        sa.Column(
            "status",
            sa.Enum(MessageStatus, name="message_status", native_enum=False, create_constraint=True),
            nullable=False,
            server_default=MessageStatus.completed.value,
        ),
    )
    op.add_column("messages", sa.Column("last_stream_at", sa.DateTime(timezone=True), nullable=True))

    # indexes
    op.create_index("ix_messages_session_created", "messages", ["session_id", "created_at"])
    op.create_index("ix_messages_session_status", "messages", ["session_id", "status"])
    op.create_index("ix_message_events_msg_seq", "message_events", ["message_id", "seq_no"])


def downgrade() -> None:
    # indexes
    op.drop_index("ix_message_events_msg_seq", table_name="message_events")
    op.drop_index("ix_messages_session_status", table_name="messages")
    op.drop_index("ix_messages_session_created", table_name="messages")

    # messages table
    op.drop_column("messages", "last_stream_at")
    op.drop_column("messages", "status")

    # sessions table
    op.drop_column("sessions", "pinned")
    op.drop_column("sessions", "title")
