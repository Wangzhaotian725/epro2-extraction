"""epro2x — offline extractor for EasyEDA Pro / JLCEDA Pro `.epro2` projects.

Public API:
    from epro2x import Epro2Project
    proj = Epro2Project.open("Board.epro2")

Or use the command line:
    python -m epro2x.extract Board.epro2 -o out/
"""

from .core import Epro2Project, EpruDoc  # noqa: F401

__version__ = "1.0.0"
__all__ = ["Epro2Project", "EpruDoc"]
