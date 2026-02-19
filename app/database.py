import os
import ssl
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required.")

# Neon connection strings use postgresql:// with query params like
# sslmode=require and channel_binding=require that asyncpg doesn't
# accept via the URL. We strip them and pass SSL via connect_args.
parsed = urlparse(DATABASE_URL)
query_params = parse_qs(parsed.query)

_needs_ssl = query_params.pop("sslmode", [None])[0] == "require"
query_params.pop("channel_binding", None)

clean_query = urlencode(query_params, doseq=True)
scheme = "postgresql+asyncpg" if parsed.scheme == "postgresql" else parsed.scheme
DATABASE_URL = urlunparse(parsed._replace(scheme=scheme, query=clean_query))

connect_args = {"ssl": ssl.create_default_context()} if _needs_ssl else {}

engine = create_async_engine(
    DATABASE_URL, echo=False, pool_pre_ping=True, connect_args=connect_args
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
