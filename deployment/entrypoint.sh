#!/bin/sh
# Migrate, then serve. `set -e` so a failed migration stops the container and the deploy stays
# unhealthy, rather than serving against a schema the application does not expect.
set -eu
echo "applying migrations..."
alembic upgrade head
echo "starting api on port ${PORT:-8000}"
exec uvicorn "market_approach_desk.api:create_app" --factory --host 0.0.0.0 --port "${PORT:-8000}"
