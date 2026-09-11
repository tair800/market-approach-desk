"""The n8n baseline arm: the exported workflow, and a faithful model of how it executes.

This package exists for one reason — so the kill-test harness can ``import n8n.simulator`` without
a path hack. It is **not** part of the shipped service and nothing under ``src/`` may import it: the
product must not know a baseline exists, and a guard test enforces that direction. The dependency
runs one way only, from the baseline to the domain, because both arms have to be measured with the
same instrument to be compared at all.
"""

from __future__ import annotations
