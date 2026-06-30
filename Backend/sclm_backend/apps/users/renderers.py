"""
SCLM Cloud — Standard JSON Envelope Renderer
Wraps ALL DRF responses in the standard envelope:
  { "status": "success|error", "data": {...}, "meta": {...} }

This renderer is registered globally in settings.REST_FRAMEWORK.
It MUST NOT be bypassed by individual views; the standard applies everywhere.
"""
import json
from rest_framework.renderers import JSONRenderer


class SCLMJSONRenderer(JSONRenderer):
    """
    Custom DRF renderer that enforces the SCLM standard API envelope.
    Views simply return their data payload; this renderer wraps it.
    """
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")
        status_code = response.status_code if response else 200

        # Determine success vs error from HTTP status code.
        is_error = status_code >= 400

        if is_error:
            envelope = {
                "status": "error",
                "error": data,
            }
        else:
            # Extract pagination meta if present (DRF list responses).
            if isinstance(data, dict) and "results" in data:
                envelope = {
                    "status": "success",
                    "data": data["results"],
                    "meta": {
                        "count": data.get("count"),
                        "next": data.get("next"),
                        "previous": data.get("previous"),
                    },
                }
            else:
                envelope = {
                    "status": "success",
                    "data": data,
                    "meta": {},
                }

        return super().render(envelope, accepted_media_type, renderer_context)
