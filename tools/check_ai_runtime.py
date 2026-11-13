"""Quietly check the embedded AI runtime without aborting the Windows launcher."""
try:
    from llama_cpp import Llama  # noqa: F401
except Exception as exc:
    print(f"Embedded AI runtime not available: {type(exc).__name__}: {exc}")
    raise SystemExit(1)
else:
    print("Embedded AI runtime verified.")
