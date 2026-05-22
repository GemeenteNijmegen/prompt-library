from typing import Any


def data_response(data: Any) -> dict:
    return {"data": data}


def paginated_response(data: list, total: int, page: int, per_page: int) -> dict:
    pages = max(1, -(-total // per_page))  # ceiling division
    return {
        "data": data,
        "meta": {"total": total, "page": page, "per_page": per_page, "pages": pages},
    }


def action_response(data: Any, action: str) -> dict:
    return {"data": data, "meta": {"action": action}}


def error_response(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}
