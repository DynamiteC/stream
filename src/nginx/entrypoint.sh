#!/bin/sh
set -e

# Inject environment variables into Nginx config
# We use a template approach or simple sed if envsubst is not available (alpine nginx has it usually)
# But standard nginx image supports /docker-entrypoint.d/ scripts for this.

# However, to be safe and explicit:
echo "Injecting SECRET_KEY into nginx.conf..."
sed -i "s/REPLACE_WITH_SECRET_KEY/${SECRET_KEY}/g" /etc/nginx/nginx.conf

# Execute the CMD
exec "$@"
