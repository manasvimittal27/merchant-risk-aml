"""Run the full pipeline: generate data -> onboarding, screening, SQL monitoring, chargebacks -> charts."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for step in ("generate_data.py", "analyze.py", "charts.py"):
    print(f"\n=== {step} ===")
    subprocess.run([sys.executable, str(ROOT / "src" / step)], check=True)
