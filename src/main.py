# Entry point for the Network Intrusion Detection System
import sys
import os
from dashboard.app import app

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
