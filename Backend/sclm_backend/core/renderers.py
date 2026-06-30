"""
core.renderers
─────────────────────────────────────────────────────────────────────────────
Standard JSON Envelope Renderer.

ALL DRF API responses are wrapped in a uniform envelope:

SUCCESS (2xx):
  {
    "status": "success",
    "data": <serializer output>,
    "pagination": {          ← only for list endpoints
      "count": 100,
      "next": "...",
      "previous": null,
      "page_size": 20,
      "current_page": 1,
      "total_pages": 5
    }
  }

ERROR (4xx / 5xx):
  {
    "status": "error",
    "error": {
      "code": "VALIDATION_ERROR",
      "message": "...",
      "details": {...}
    }
  }

Configured as DEFAULT_RENDERER_CLASSES in settings/base.py.
─────────────────────────────────────────────────────────────────────────────
"""
import json
from rest_framework.renderers import JSONRenderer


class JSONEnvelopeRenderer(JSONRenderer):
    """
    Wraps every DRF response in the standard SCLM Cloud envelope.
    Strips the DRF default structure and replaces it with our own.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")
        view = renderer_context.get("view")

        if response is None:
            return super().render(data, accepted_media_type, renderer_context)

        status_code = response.status_code

        if status_code >= 400:
            envelope = self._build_error_envelope(data, status_code)
        else:
            envelope = self._build_success_envelope(data, view)

        return super().render(envelope, accepted_media_type, renderer_context)

    @staticmethod
    def _build_success_envelope(data: dict, view=None) -> dict:
        """Builds the success envelope, extracting pagination metadata if present."""
        # DRF pagination wraps data in {"count": ..., "results": [...]}
        if isinstance(data, dict) and "results" in data and "count" in data:
            return {
                "status": "success",
                "data": data["results"],
                "pagination": {
                    "count": data.get("count"),
                    "next": data.get("next"),
                    "previous": data.get("previous"),
                    "page_size": data.get("page_size", 20),
                },
            }
        return {"status": "success", "data": data}

    @staticmethod
    def _build_error_envelope(data, status_code: int) -> dict:
        """
        Builds the error envelope with a normalised code + message structure.
        Handles DRF's various error formats:
          {"detail": "..."}, {"field": ["error"]}, {"non_field_errors": [...]}
        """
        code_map = {
            400: "VALIDATION_ERROR",
            401: "AUTHENTICATION_REQUIRED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMIT_EXCEEDED",
            500: "INTERNAL_SERVER_ERROR",
        }
        code = code_map.get(status_code, f"HTTP_{status_code}")

        # Extract a human-readable top-level message.
        if isinstance(data, dict):
            message = (
                data.get("detail")
                or data.get("message")
                or f"Request failed with status {status_code}."
            )
            # 'detail' is already the message — put remaining fields in details.
            details = {k: v for k, v in data.items() if k not in ("detail", "message")}
        elif isinstance(data, list):
            message = "; ".join(str(e) for e in data)
            details = {}
        else:
            message = str(data) if data else f"HTTP {status_code}"
            details = {}

        return {
            "status": "error",
            "error": {
                "code": code,
                "message": message if isinstance(message, str) else str(message),
                "details": details,
            },
        }
