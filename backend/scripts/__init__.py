"""Standalone operator/CI scripts -- not part of the FastAPI application
package (`app`). Each script here is invoked directly (`python
scripts/<name>.py ...`, cwd=backend), the same way
scripts/postgres_ci_gate.py already is; this `__init__.py` exists only so
tests/ can import their shared library modules (pg_backup_lib,
pg_backup_verify) as `scripts.<module>` rather than manipulating
sys.path directly.
"""
