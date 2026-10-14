"""Deterministic offline evaluation of recorded graph-construction and retrieval/answer outputs.

Stdlib only. Nothing in this package calls a model, a network service or a graph database: it scores
records that some other process already produced, against gold that was authored independently.
"""

SCORER_VERSION = "zoop-eval-0.1.0"
