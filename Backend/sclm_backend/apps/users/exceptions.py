"""
SCLM Cloud — Global Exception Handler
Returns all errors in the standard SCLM envelope format:
  { "status": "error", "error": { "code": "...", "message": "...", "details": {...} } }
"""
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def sclm_exception_handler(exc, context):
    """
    Custom DRF exception handler. Called for all unhandled exceptions.
    Wraps the error in the SCLM standard envelope.
    """
    # Let DRF handle the exception first to get the standard response object.
    response = exception_handler(exc, context)

    if response is not None:
        # Map DRF status codes to human-readable error codes.
        error_code_map = {
            400: "VALIDATION_ERROR",
            401: "AUTHENTICATION_REQUIRED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMIT_EXCEEDED",
        }

        error_code = error_code_map.get(response.status_code, "API_ERROR")

        # The renderer will wrap this in {"status": "error", "error": ...}
        response.data = {
            "code": error_code,
            "message": _extract_message(response.data),
            "details": response.data if not isinstance(response.data, str) else {},
        }
    else:
        # Unhandled server error — log it and return a sanitized 500.
        logger.exception("Unhandled server exception: %s", exc)
        response = Response(
            {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Our team has been notified.",
                "details": {},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response


def _extract_message(data):
    """Extract a human-readable message string from DRF error data."""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return data[0] if data else "Validation error."
    if isinstance(data, dict):
        # DRF validation errors: {"field": ["error msg"]}
        for key, value in data.items():
            if key == "detail":
                return str(value)
            if isinstance(value, list) and value:
                return f"{key}: {value[0]}"
    return "An error occurred."
