"""
Pipeline runner for streaming inference.
"""

import os

STUB_MODELS = os.getenv("STUB_MODELS", "false").lower() == "true"

