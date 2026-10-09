"""Local development entry point: python -m app."""

from . import create_app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=app.config["SERVER_HOST"],
        port=app.config["SERVER_PORT"],
        debug=app.config["DEBUG"],
        load_dotenv=False,
    )
