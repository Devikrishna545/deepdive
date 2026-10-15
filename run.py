"""Dev entry point: `python run.py` starts the API and web UI on http://127.0.0.1:8000."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app:create_app", factory=True, host="127.0.0.1", port=8000, reload=True)
