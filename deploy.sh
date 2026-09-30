#!/bin/bash
# Deploy manual en la instancia EC2: trae el código y reconstruye el contenedor.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

git pull
docker compose up --build -d
