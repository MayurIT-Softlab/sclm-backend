#!/usr/bin/env python
"""
SCLM Cloud — Django Management Utility
"""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sclm_backend.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you inside the pipenv shell? "
            "Run: pipenv shell"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
