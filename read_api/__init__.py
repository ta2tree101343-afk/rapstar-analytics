# This __init__.py makes `read_api` importable as a Python package during
# local development and tests (e.g. `from read_api import handler`). It is
# not required at Lambda runtime — SAM's `CodeUri: ../read_api/` packages
# files at the ZIP root, and `handler.py` uses absolute imports.
