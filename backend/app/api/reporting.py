from flask import request

from . import api
from ..services.record_queries import categories, statistics


@api.get("/stats")
def query_stats():
    return statistics(request.args)


@api.get("/categories")
def query_categories():
    return categories(request.args)
