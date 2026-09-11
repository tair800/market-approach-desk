#!/bin/sh
# Migrate, then serve. `set -e` so a failed migration stops the container and the deploy stays
# unhealthy, rather than serving against a schema the application does not expect.
set -eu
echo "applying migrations..."
alembic upgrade head
# Seed the demonstration on a genuinely empty database, and only then. This never deletes
# anything — see demo/seed.py::bootstrap — so a restart or a redeploy is a no-op and whatever a
# visitor did to the board survives it.
if [ "${MAD_DEMO_MODE:-false}" = "true" ]; then
  echo "bootstrapping the demonstration..."
  python -m market_approach_desk.demo.bootstrap
fi
echo "starting api on port ${PORT:-8000}"
exec uvicorn "market_approach_desk.api:create_app" --factory --host 0.0.0.0 --port "${PORT:-8000}"
