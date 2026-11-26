from alembic import context
from sqlalchemy import Connection


def run() -> None:
    connection = context.config.attributes.get("connection")
    if not isinstance(connection, Connection):
        raise RuntimeError("Migrations require an application database connection.")
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


run()
