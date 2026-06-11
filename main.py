"""Thin entrypoint so `python main.py`, `uvicorn main:app` and the Docker CMD keep working.

The application lives in the `app` package (config, schemas, probe, downloads, routes).
"""

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    from app.config import HOST, PORT

    uvicorn.run(app, host=HOST, port=PORT)
