"""Fail-closed runtime configuration. Errors name settings, never their values."""
import os
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

class ConfigurationError(RuntimeError):
    pass


def load_environment():
    """Hosted environments must use platform settings, never development .env files."""
    mode = os.environ.get('APP_ENV', 'development').strip().lower()
    if mode not in {'development', 'test', 'production'}:
        raise ConfigurationError('APP_ENV must be development, test or production')
    managed_host = os.environ.get('RENDER', '').lower() == 'true' or bool(os.environ.get('RAILWAY_ENVIRONMENT_ID'))
    if mode != 'production' and not managed_host:
        load_dotenv(override=False)


load_environment()


def required_env(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ConfigurationError(f'{name} must be configured explicitly')
    return value


def database_url():
    value = required_env('DATABASE_URL').strip()
    try:
        url = make_url(value)
        if url.drivername not in {'postgres', 'postgresql', 'postgresql+psycopg'} or not url.host or not url.database:
            raise ValueError()
        url = url.set(drivername='postgresql+psycopg')
    except Exception:
        raise ConfigurationError('DATABASE_URL must be a valid PostgreSQL connection URL') from None
    # Select the declared psycopg driver, preserving host, port, database and credentials.
    return url


def jwt_secret():
    value = required_env('JWT_SECRET_KEY')
    if value in {'default_if_missing', 'change-me', 'your-secret-key'}:
        raise ConfigurationError('JWT_SECRET_KEY must not be a known development placeholder')
    # Keep existing key bytes exactly: trimming or selecting SECRET_KEY could log users out.
    # SECRET_KEY was not used by the prior auth implementation; it is not a safe alias.
    return value
