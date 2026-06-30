"""
core.exceptions
Custom DRF exception handler that routes all errors through the envelope renderer.
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.exceptions import APIException
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def sclm_exception_handler(exc, context):
    """
    Custom exception handler. Delegates to DRF's default handler first,
    then ensures the error envelope format is consistent.
    Handles Django ValidationError (raised by model.clean()) as a 400.
    """
    # Convert Django ValidationError → DRF ValidationError
    if isinstance(exc, DjangoValidationError):
        from rest_framework.exceptions import ValidationError
        exc = ValidationError(detail=exc.message_dict if hasattr(exc, 'message_dict') else list(exc.messages))

    # Convert service-layer ValueError → DRF ValidationError (400)
    if isinstance(exc, ValueError):
        from rest_framework.exceptions import ValidationError
        exc = ValidationError(detail=str(exc))

    # Let DRF handle the rest
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception → 500
        logger.error(
            "Unhandled exception in view '%s': %s",
            context.get("view"),
            exc,
            exc_info=True,
        )
        return Response(
            {
                "status": "error",
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred.",
                    "details": {},
                },
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response
