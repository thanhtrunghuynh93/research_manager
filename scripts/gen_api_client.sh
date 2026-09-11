#!/usr/bin/env bash
# Export the OpenAPI schema from the app and regenerate the TypeScript client.
# CI runs this and fails on any diff (client-drift job).
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p docs/api frontend/src/api/generated
(cd backend && uv run python - <<'PY'
import json
from app.main import create_app
from app.core.config import Settings
app = create_app(Settings(env="test", secret_key="gen"))  # type: ignore[arg-type]
json.dump(app.openapi(), open("../docs/api/openapi.json", "w"), indent=2, sort_keys=True)
print("wrote docs/api/openapi.json")
PY
)
(cd frontend && npx --yes openapi-typescript@7 ../docs/api/openapi.json -o src/api/generated/schema.d.ts)
echo "wrote frontend/src/api/generated/schema.d.ts"
