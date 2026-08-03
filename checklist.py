# save as check_setup.py and run: python check_setup.py

import importlib, sys

packages = [
    "yfinance", "pandas", "numpy", "ta",
    "streamlit", "plotly", "schedule", "apscheduler",
    "sqlalchemy", "dotenv", "loguru", "telegram",
    "google.generativeai", "groq", "anthropic", "requests"
]

print("Checking your setup...\n")
all_ok = True
for pkg in packages:
    try:
        importlib.import_module(pkg)
        print(f"  ✅  {pkg}")
    except ImportError:
        print(f"  ❌  {pkg}  ← needs install")
        all_ok = False

print()
print("✅ All good! Ready to build." if all_ok else 
      "❌ Fix the missing packages above first.")