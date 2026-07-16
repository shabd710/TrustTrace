"""
Shared pytest path setup.

'threat-intel' is a hyphenated directory (matches the PDF spec's literal
monorepo layout exactly) and therefore cannot be a Python package -- see
the note in threat-intel/campaign_graph.py. This conftest adds it (and the
repo root) to sys.path once, for every test file, the same way
backend/api/routes.py does at runtime.
"""
import sys
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "threat-intel"))
sys.path.insert(0, os.path.join(REPO_ROOT, "federated"))
