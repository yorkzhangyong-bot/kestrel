"""The experience store (feature 004): a local ChromaDB collection of attack patterns and per-target memory.

Closes Principle V — every run writes back. This package owns everything ChromaDB: the store wrapper, the
one-line situation summary (built and sanitised without a model call), and the attacker hint block. No attack
prompt text lives here; patterns and memory are data the store holds at run time, never written into this code.
"""
