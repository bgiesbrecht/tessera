"""Exploratory spikes for the change-impact tool. NOT production checks.

These prototypes probe whether richer techniques (graph queries over the corpus;
enumerating the abstract request space) buy us more than the shipped C1–C6 / L1
/ L2 checks, per the design conversation on Layers 1–2 of change-impact
analysis. They are deliberately separate from `tools/impact/checks.py`: kept
here so they can be evaluated and thrown away or promoted without disturbing the
shipped tool.
"""
