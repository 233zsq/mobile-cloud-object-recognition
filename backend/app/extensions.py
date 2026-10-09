"""Database integration; connections are opened only when used."""

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import URL, make_url
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def init_database(app):
    app.config.setdefault(
        "SQLALCHEMY_DATABASE_URI",
        URL.create(
            "mysql+pymysql",
            username=app.config["DB_USER"],
            password=app.config["DB_PASSWORD"],
            host=app.config["DB_HOST"],
            port=app.config["DB_PORT"],
            database=app.config["DB_NAME"],
            query={"charset": "utf8mb4"},
        ),
    )
    url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if url.get_backend_name() == "mysql":
        options.update(
            pool_recycle=1800,
            connect_args={
                "connect_timeout": 5,
                "read_timeout": 10,
                "write_timeout": 10,
                "init_command": "SET time_zone = '+00:00'",
            },
        )
    options.update(app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}))
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = options
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
