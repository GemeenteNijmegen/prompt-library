"""Tests for Settings — DATABASE_URL assembly and validation."""
import os
import pytest


def _make_settings(**overrides):
    """Return a fresh Settings instance with env vars isolated to this call."""
    # Strip any DATABASE_* vars the outer test process may have set, then apply overrides.
    clean = {
        k: v for k, v in os.environ.items()
        if not k.startswith("DATABASE_")
    }
    clean.update(overrides)
    # Pydantic-settings reads from the environment, so we patch it temporarily.
    original = {k: os.environ.get(k) for k in overrides}
    for k, v in overrides.items():
        os.environ[k] = str(v)
    for k in list(os.environ):
        if k.startswith("DATABASE_") and k not in overrides:
            os.environ.pop(k, None)

    try:
        # Import fresh so pydantic-settings re-reads env.
        import importlib
        import src.config as cfg_mod
        importlib.reload(cfg_mod)
        from src.config import Settings
        return Settings()
    finally:
        # Restore original env.
        for k, orig in original.items():
            if orig is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = orig


class TestDatabaseUrlDirect:
    def test_default_is_sqlite(self):
        from src.config import Settings
        s = Settings(DATABASE_URL="sqlite:///data/gallery.db", DATABASE_HOST="")
        assert s.DATABASE_URL == "sqlite:///data/gallery.db"

    def test_explicit_url_is_preserved_when_no_host(self):
        s = _make_settings(DATABASE_URL="postgresql+psycopg2://user:pass@host/db")
        assert s.DATABASE_URL == "postgresql+psycopg2://user:pass@host/db"


class TestDatabaseUrlAssembly:
    def test_assembles_from_parts(self):
        from src.config import Settings
        from sqlalchemy.engine import make_url
        s = Settings(
            DATABASE_HOST="db.example.com",
            DATABASE_PORT=5432,
            DATABASE_USERNAME="myuser",
            DATABASE_PASSWORD="mypassword",
            DATABASE_NAME="mydb",
        )
        url = make_url(s.DATABASE_URL)
        assert url.drivername == "postgresql+psycopg2"
        assert url.username == "myuser"
        assert url.password == "mypassword"
        assert url.host == "db.example.com"
        assert url.port == 5432
        assert url.database == "mydb"

    def test_special_chars_in_password_are_percent_encoded(self):
        """Passwords with =, ^, @, / must be percent-encoded in the URL string
        so the URL is parseable, but round-trip via make_url recovers the raw value."""
        from src.config import Settings
        from sqlalchemy.engine import make_url
        s = Settings(
            DATABASE_HOST="host",
            DATABASE_PORT=5432,
            DATABASE_USERNAME="user",
            DATABASE_PASSWORD="=p@ss/w0rd^",
            DATABASE_NAME="db",
        )
        # Raw password must not appear literally in the URL string (@ would break parsing).
        assert "=p@ss/w0rd^" not in s.DATABASE_URL
        assert "@host" in s.DATABASE_URL
        # Round-trip recovers the original password.
        assert make_url(s.DATABASE_URL).password == "=p@ss/w0rd^"

    def test_password_with_percent_sign(self):
        """A literal % in the password must survive the round-trip."""
        from src.config import Settings
        from sqlalchemy.engine import make_url
        s = Settings(
            DATABASE_HOST="host",
            DATABASE_PORT=5432,
            DATABASE_USERNAME="user",
            DATABASE_PASSWORD="p%ass",
            DATABASE_NAME="db",
        )
        assert make_url(s.DATABASE_URL).password == "p%ass"

    def test_host_takes_priority_over_explicit_database_url(self):
        """If DATABASE_HOST is provided alongside DATABASE_URL, components win."""
        from src.config import Settings
        s = Settings(
            DATABASE_URL="sqlite:///should-be-overridden.db",
            DATABASE_HOST="pg.example.com",
            DATABASE_PORT=5432,
            DATABASE_USERNAME="u",
            DATABASE_PASSWORD="p",
            DATABASE_NAME="mydb",
        )
        assert s.DATABASE_URL.startswith("postgresql+psycopg2://")

    def test_custom_port(self):
        from src.config import Settings
        s = Settings(
            DATABASE_HOST="host",
            DATABASE_PORT=5433,
            DATABASE_USERNAME="u",
            DATABASE_PASSWORD="p",
            DATABASE_NAME="db",
        )
        from sqlalchemy.engine import make_url
        assert make_url(s.DATABASE_URL).port == 5433
