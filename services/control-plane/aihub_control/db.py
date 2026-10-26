from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import Settings


class Base(DeclarativeBase):
    pass


def make_session_factory(settings: Settings | None = None):
    settings = settings or Settings()
    url = settings.sync_database_url
    kwargs = {"pool_pre_ping": True, "pool_size": 20, "max_overflow": 20} if url.startswith("postgresql") else {}
    engine = create_engine(url, **kwargs)
    return engine, sessionmaker(engine, expire_on_commit=False)


try:
    _default_settings = Settings()
except ValueError:
    # Importing models and pure unit-test modules must remain possible.  The
    # application factory still validates configuration before serving traffic.
    _default_settings = None

engine = None
SessionLocal = None
if _default_settings is not None:
    engine, SessionLocal = make_session_factory(_default_settings)


def get_session_factory():
    global engine, SessionLocal
    if SessionLocal is None:
        engine, SessionLocal = make_session_factory(Settings())
    return engine, SessionLocal
