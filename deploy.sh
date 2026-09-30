#!/bin/bash
# Deploy manual en la instancia EC2: trae el código y reconstruye el contenedor.
#
# `git reset --hard` en vez de `git pull`: un deploy no debe fallar por un
# conflicto de merge si algo se tocó a mano en el servidor. La rama remota es
# siempre la verdad; cualquier cambio local en la instancia se descarta —
# incluido este mismo archivo si se editara sin commitear, así que cualquier
# cambio a deploy.sh se prueba y se sube a git ANTES de volver a correrlo.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Falla rápido y con un mensaje claro, no a mitad del build. El error típico
# aquí es que `usermod -aG docker $USER` se corrió, pero la sesión SSH actual
# es anterior a ese cambio: los grupos de un proceso se fijan al iniciar
# sesión, así que "agregarse al grupo" no alcanza al usuario ya conectado.
if ! docker info > /dev/null 2>&1; then
  cat >&2 <<'EOF'
✗ No se puede hablar con Docker (permiso denegado en /var/run/docker.sock).

Solución en dos pasos, en la instancia:
  1. sudo usermod -aG docker "$USER"     (una sola vez, si no se hizo ya)
  2. Cerrar esta sesión SSH y volver a entrar (o: newgrp docker)
     — el grupo no se aplica a una sesión que ya estaba abierta.

Verifica con: docker ps   (sin sudo, debe responder sin error)
EOF
  exit 1
fi

git fetch origin main
git reset --hard origin/main

docker compose up --build -d

# Sin esto, cada deploy deja la imagen anterior como <none> y el disco de la
# instancia se llena en semanas de iteración.
docker image prune -f
