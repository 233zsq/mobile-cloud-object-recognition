"""JSON errors; retain HTTP headers such as Allow and Retry-After."""

from flask import Flask, g
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError


class ApiError(Exception):
    """An expected business error with a public message."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def register_error_handlers(app: Flask) -> None:
    def body(code: str, message: str) -> dict:
        return {
            "error": {"code": code, "message": message},
            "request_id": g.request_id,
        }

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return body(error.code, error.message), error.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        response = error.get_response()
        response.data = app.json.dumps(
            body(error.name.upper().replace(" ", "_"), error.description)
        )
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("Unhandled exception request_id=%s", g.request_id)
        return body("INTERNAL_SERVER_ERROR", "服务器内部错误，请凭请求编号联系维护人员。"), 500

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error: SQLAlchemyError):
        from .extensions import db
        db.session.rollback()
        app.logger.exception("Database operation failed request_id=%s", g.request_id)
        return body("DATABASE_UNAVAILABLE", "数据库暂不可用，请稍后使用相同UUID重试。"), 503
