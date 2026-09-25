"""FarLink Agent Launcher."""
import os
import sys

# Ensure python directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from app.main import main
    main()
