# Dans test1/models/__init__.py

from .centre import Centre
from .concour import Concours
from .candidat import Candidat
from .inscriptions import Inscription

__all__ = [
    "Concours",
    "Centre",
    "Candidat",
    "Inscription",
]