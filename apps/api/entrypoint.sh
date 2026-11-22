#!/bin/sh
set -e

# Run database migrations if RUN_MIGRATIONS is true (default true)
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "Running database schema migrations via Alembic..."
    alembic upgrade head
    echo "Alembic migrations completed successfully."
fi

exec "$@"
