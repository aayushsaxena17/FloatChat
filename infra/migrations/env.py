import os

from alembic import context
from sqlalchemy import create_engine, pool

url = os.environ["DATABASE_ADMIN_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
