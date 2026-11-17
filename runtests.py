#!/usr/bin/env python
"""Run the aa-ticket test suite: python runtests.py aa_ticket -v 2"""

import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "testauth.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(["manage.py", "test", *sys.argv[1:]])
