#!/usr/bin/env bash
# contract-drift (PRD §10.4, ADR-10): regenera o contrato a partir do OpenAPI atual do
# engine e falha se o resultado divergir do que está versionado em packages/api-types.
set -euo pipefail
cd "$(dirname "$0")/.."

npm run --silent contract:generate >/dev/null

if [ -n "$(git status --porcelain -- packages/api-types)" ]; then
  echo "::error::O contrato gerado diverge do versionado. Rode 'npm run contract:generate' e faça commit de packages/api-types."
  git status --porcelain -- packages/api-types
  git --no-pager diff --stat -- packages/api-types
  exit 1
fi
echo "Contrato em dia com o OpenAPI do engine."
