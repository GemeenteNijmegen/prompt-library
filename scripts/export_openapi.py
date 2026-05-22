#!/usr/bin/env python3
"""Export the FastAPI OpenAPI spec to openapi/openapi.json."""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from src.main import create_app

app = create_app()
spec = app.openapi()

out = Path("openapi/openapi.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(spec, indent=2) + "\n")
print(f"Wrote {out} ({len(spec['paths'])} paths)")
