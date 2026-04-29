# Entry point for the Network Intrusion Detection System
import sys

# Ensure project root is importable when running as python src/main.py.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import os

if __name__ == "__main__":
    from dashboard.app import app

    app.run(host="0.0.0.0", port=5000, debug=False)
