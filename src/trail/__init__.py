"""Trail — record how notebook code evolves, and explain the optimisations.

The public notebook API (``trail.start`` and friends, SPEC section 9) arrives in
Milestone 1. Right now this module only carries the version so that packaging,
imports and the test harness can be verified end to end.
"""

from trail._version import __version__

__all__ = ["__version__"]
