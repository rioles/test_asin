"""
Client du service national d'identification (GET /identite/{npi}).

INC-206 : le client HTTP standard, dans sa configuration par défaut, n'a AUCUN
délai d'attente. Un service lent (22 s dans le journal) bloquait donc les
workers du serveur : plus personne ne pouvait s'inscrire ni consulter sa
convocation.

Ici :
  * l'appel s'exécute dans un pool de threads dédié et l'appelant n'attend
    jamais plus de IDENTITE_DELAI_S (5 s) au total : connexion, envoi, lecture
    et attente d'un thread libre compris (un simple `timeout` socket ne suffit
    pas : il s'applique à CHAQUE lecture, pas à l'appel entier) ;
  * le même délai est posé sur le socket, pour que le thread abandonné se
    libère lui aussi ;
  * aucune exception ne remonte : l'appelant reçoit TROUVE, INCONNU ou
    INDISPONIBLE et décide (INDISPONIBLE => inscription « en attente »).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from enum import Enum

from django.conf import settings

logger = logging.getLogger("inscriptions.identite")

_executor = ThreadPoolExecutor(max_workers=32, thread_name_prefix="identite")
_TAILLE_MAX_REPONSE = 64 * 1024


class StatutIdentite(str, Enum):
    TROUVE = "TROUVE"
    INCONNU = "INCONNU"          # le service répond que le NPI n'existe pas (404)
    INDISPONIBLE = "INDISPONIBLE"  # délai dépassé, erreur réseau, 5xx, réponse illisible


@dataclass(frozen=True)
class ResultatIdentite:
    statut: StatutIdentite
    nom: str = ""
    prenoms: str = ""


def _delai() -> float:
    return float(getattr(settings, "IDENTITE_DELAI_S", 5.0))


def _appel_http(npi: str, delai: float) -> tuple[ResultatIdentite, int | None]:
    base = settings.IDENTITE_BASE_URL.rstrip("/")
    url = f"{base}/identite/{urllib.parse.quote(npi, safe='')}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=delai) as rep:
            donnees = json.loads(rep.read(_TAILLE_MAX_REPONSE))
            return (
                ResultatIdentite(
                    StatutIdentite.TROUVE,
                    nom=str(donnees.get("nom", ""))[:60],
                    prenoms=str(donnees.get("prenoms", ""))[:80],
                ),
                rep.status,
            )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ResultatIdentite(StatutIdentite.INCONNU), 404
        return ResultatIdentite(StatutIdentite.INDISPONIBLE), e.code
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        # URLError, socket.timeout/TimeoutError, connexion refusée, JSON invalide…
        return ResultatIdentite(StatutIdentite.INDISPONIBLE), None


def verifier_identite(npi: str) -> ResultatIdentite:
    """Interroge le service ; rend toujours la main en moins de IDENTITE_DELAI_S."""
    delai = _delai()
    debut = time.monotonic()
    futur = _executor.submit(_appel_http, npi, delai)
    try:
        resultat, code = futur.result(timeout=delai)
    except FuturesTimeout:
        futur.cancel()  # s'il attendait encore un thread libre, il ne partira pas
        resultat, code = ResultatIdentite(StatutIdentite.INDISPONIBLE), None

    duree_ms = int((time.monotonic() - debut) * 1000)
    niveau = logging.WARNING if duree_ms >= delai * 1000 else logging.INFO
    logger.log(
        niveau,
        "appel identite GET /identite/%s -> %s (%d ms)",
        npi, code if code is not None else "timeout/erreur", duree_ms,
    )
    return resultat
