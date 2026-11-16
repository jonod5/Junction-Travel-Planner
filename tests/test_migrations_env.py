"""Database URL handling shared by the app and Alembic (post-audit BUG-02).

Alembic failed on Railway after a rebuild picked up SQLAlchemy 2.1, whose
default driver for a plain "postgresql://" URL is psycopg (v3) — not
installed — while the app kept working because app/db.py rewrote the scheme
and alembic/env.py did not.
"""

import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest  # noqa: E402

from app.db import Base, normalize_database_url  # noqa: E402

ENV_PY = Path(__file__).resolve().parent.parent / "alembic" / "env.py"


@pytest.mark.parametrize("url,expected", [
    ("postgresql://u:p@host:5432/db", "postgresql+psycopg2://u:p@host:5432/db"),
    ("postgresql+psycopg2://u:p@host/db", "postgresql+psycopg2://u:p@host/db"),
    ("sqlite://", "sqlite://"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_normalize_database_url(url, expected):
    assert normalize_database_url(url) == expected


def test_only_the_scheme_is_rewritten():
    # A password containing the scheme text must survive untouched.
    assert normalize_database_url("postgresql://u:postgresql://@h/db") == "postgresql+psycopg2://u:postgresql://@h/db"


def test_alembic_env_uses_the_shared_normalizer():
    source = ENV_PY.read_text()
    assert "normalize_database_url(os.environ[\"DATABASE_URL\"])" in source
    assert 'config.set_main_option("sqlalchemy.url", os.environ' not in source


def test_every_model_module_is_registered_with_alembic():
    """If a model module isn't imported by env.py its tables are missing from
    Base.metadata there, and `alembic revision --autogenerate` would propose
    dropping them."""
    import importlib
    import pkgutil

    import app.models

    source = ENV_PY.read_text()
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")
        assert f"app.models.{module.name}" in source, f"alembic/env.py does not import app.models.{module.name}"
    assert {"trip", "stop", "leg"} <= set(Base.metadata.tables)
