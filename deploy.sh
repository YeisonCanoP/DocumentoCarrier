#!/bin/bash
# Deploy manual en la instancia EC2: trae el código y reconstruye el contenedor.
#
# `git reset --hard` en vez de `git pull`: un deploy no debe fallar por un
# conflicto de merge si algo se tocó a mano en el servidor. La rama remota es
# siempre la verdad; cualquier cambio local en la instancia se descarta.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

git fetch origin main
git reset --hard origin/main

docker compose up --build -d

# Sin esto, cada deploy deja la imagen anterior como <none> y el disco de la
# instancia se llena en semanas de iteración.
docker image prune -f
