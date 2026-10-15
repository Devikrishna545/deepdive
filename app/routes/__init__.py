"""Routers (the FastAPI equivalent of Flask blueprints).

pages.py      GET /, GET /runs/{id}                 HTML pages (Jinja2 templates)
health.py     GET /api/health                       liveness + config sanity (never echoes keys)
api_runs.py   /api/runs ...                         start runs, stream progress, report, claims, trail, export
api_files.py  /api/files ...                        upload documents for grounding
"""
