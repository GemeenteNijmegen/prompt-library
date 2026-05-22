#!/usr/bin/env python3
"""Build a minimal GitHub Pages site with Swagger UI for the OpenAPI spec."""
import json
import shutil
from pathlib import Path

SPEC = Path("openapi/openapi.json")
OUT = Path("_site")

spec = json.loads(SPEC.read_text())
title = spec.get("info", {}).get("title", "API Docs")

shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir()

shutil.copy(SPEC, OUT / "openapi.json")

(OUT / "index.html").write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>{title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({{
      url: "openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
    }});
  </script>
</body>
</html>
""")

print(f"Built {OUT}/index.html")
