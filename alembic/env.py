import os

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import Table, Column, Integer

from alembic import context

from davai_s_nami_bot.database.models import Base
from sqlalchemy.schema import MetaData

database_url = os.environ["DSN_DATABASE_URL"] or "sqlite:///:memory:"
TABLES_TO_EXCLUDE = [
    #'place_place', 'events_events2post',
    'events_eventsnotapprovednew',
    'bot_user_events',
]

alembic_metadata = MetaData()

# Копируем только нужные таблицы из Base.metadata
for table in Base.metadata.sorted_tables:
    if table.name not in TABLES_TO_EXCLUDE:
        # Важно: используйте 'reflect' или 'copy' для пересоздания объекта Table
        # В данном случае, самый простой подход - это создать словарь
        # и затем использовать его.

        # Более чистый подход (используя API SQLAlchemy):
        table.to_metadata(alembic_metadata)

# Устанавливаем целевые метаданные для Alembic


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

target_metadata = alembic_metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

DJANGO_OWNED_TABLES = {
    # Зеркалим в SQLAlchemy моделях для FK/lookup'ов,
    # но схемой управляет Django (app `category`).
    'category_category',
    'category_subcategory',
}


def include_object(object, name, type_, reflected, compare_to):
    """
    Эта функция вызывается для каждого объекта, который Alembic находит.
    Возвращает True, если объект нужно обрабатывать, и False, если игнорировать.
    """

    # Если это таблица и она пришла из базы данных (reflected=True),
    # но её НЕТ в наших моделях (target_metadata) -> ИГНОРИРУЕМ ЕЁ.
    if type_ == "table" and reflected:
        if name not in target_metadata.tables:
            return False

    # Django-owned таблицы — отзеркалены в моделях, но миграции не пишем.
    if type_ == "table" and name in DJANGO_OWNED_TABLES:
        return False
    if type_ in ("column", "index", "unique_constraint", "foreign_key_constraint"):
        table_name = getattr(getattr(object, 'table', None), 'name', None)
        if table_name in DJANGO_OWNED_TABLES:
            return False

    return True


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()



