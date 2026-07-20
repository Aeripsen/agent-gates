"""A small intake engine: one shared discover -> fetch -> sanitize -> ground -> store spine.

See tools/engine/README.md for the design. Adapters are thin per-source fetchers under
adapters/. Inference (extraction/ranking) routes through tools/llm_router.py (free models);
a deterministic substring-validation gate (ground.py) makes that safe. All external content
is treated as hostile and is sanitized (sanitize.py) before any model sees it.
"""
