"""
Enregistrement d'une inscription (POST /api/inscriptions), étapes 2 à 8.

Garanties, même avec des requêtes simultanées :
  * pas de numéro de table en double (INC-201)
  * pas de dépassement de capacité (INC-202)
  * pas de double inscription, ni au même concours ni le même jour (INC-203)
  * le service d'identification ne bloque jamais plus de 5 s (INC-206)

Comment :
  * Capacité + numéro (étapes 5 et 6) : UN SEUL UPDATE conditionnel
        UPDATE centres SET inscrits = inscrits + 1,
                           dernier_numero = dernier_numero + 1
        WHERE id = :centre AND inscrits < capacite
    PostgreSQL verrouille la ligne du centre : deux transactions ne peuvent pas
    lire le même compteur. 0 ligne modifiée = centre plein. La contrainte CHECK
    inscrits <= capacite reste un filet de sécurité.
    L'ancien « COUNT puis MAX + 1 » lisait sans verrou : deux requêtes voyaient
    la même valeur → P-0464 en double, 307 inscrits pour 300 places.
  * Doublons (étape 4) : le pré-contrôle sert à donner un message clair et à
    éviter un appel inutile au service ; la vraie garantie est l'index unique
    (npi, date_epreuve). La requête perdante reçoit une IntegrityError, sa
    transaction est annulée (compteur du centre compris) et elle rejoue
    l'inscription existante.
  * Identification (étape 7) : appelée AVANT la transaction, jamais pendant.
    Sinon le verrou du centre serait gardé jusqu'à 5 s et toutes les
    inscriptions du centre attendraient.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from ..models import Candidat, Centre, Concours, Inscription
from .identite_client import StatutIdentite, verifier_identite

AGE_MAX = 35


class InscriptionRefusee(Exception):
    def __init__(self, code: str, message: str, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass
class ResultatInscription:
    inscription: Inscription
    creee: bool  # False = rejeu d'une inscription identique (double clic)


# ---------------------------------------------------------------------------
# Règles pures (testables sans base)
# ---------------------------------------------------------------------------
def age_au_31_decembre(date_naissance: date, annee: int) -> int:
    """Âge révolu au 31 décembre de `annee`.

    INC-205 : l'ancien calcul « jours / 365 » ignorait les années bissextiles et
    comptait les fractions d'année (né le 20/06/1991 → 35,5 > 35 → refus à tort).
    Au 31 décembre, l'anniversaire de l'année est forcément passé.
    """
    fin = date(annee, 12, 31)
    return fin.year - date_naissance.year - (
        (fin.month, fin.day) < (date_naissance.month, date_naissance.day)
    )


def est_cloture(concours: Concours, maintenant: datetime | None = None) -> bool:
    """INC-204 : comparaison d'instants, pas d'heures « murales ».

    L'ancien code comparait l'heure locale du serveur (Bénin, GMT+1) à la valeur
    UTC lue en base, sans fuseau : la clôture de 23 h 59 tombait à 22 h 59.
    Ici les deux valeurs sont des datetime « aware » ; le fuseau du serveur
    n'intervient plus.
    """
    maintenant = maintenant or timezone.now()
    cloture = concours.cloture
    if timezone.is_naive(cloture):  # colonne sans fuseau : la valeur est en UTC
        cloture = cloture.replace(tzinfo=dt_timezone.utc)
    return maintenant > cloture


# ---------------------------------------------------------------------------
# Inscription
# ---------------------------------------------------------------------------
def _inscription_active_du_jour(npi: str, concours: Concours) -> Inscription | None:
    return (
        Inscription.objects.select_related("concours", "centre")
        .filter(npi=npi, date_epreuve=concours.date_epreuve)
        .exclude(statut=Inscription.Statut.ANNULEE)
        .first()
    )


def _rejouer_ou_refuser(existante: Inscription, concours: Concours, centre: Centre):
    if existante.concours_id == concours.id:
        if existante.centre_id == centre.id:
            # Double clic sur « Valider » (INC-203) : on renvoie la même
            # inscription au lieu d'en créer une seconde.
            return ResultatInscription(existante, creee=False)
        raise InscriptionRefusee(
            "DEJA_INSCRIT",
            f"Ce candidat est déjà inscrit à ce concours "
            f"(centre {existante.centre.code}, n° {existante.numero_table}).",
            409,
        )
    # Règle métier, pas une anomalie (cf. INC-208).
    raise InscriptionRefusee(
        "MEME_JOUR",
        f"Ce candidat est déjà inscrit au concours {existante.concours.code}, "
        f"dont l'épreuve a lieu le même jour.",
        409,
    )


def inscrire(
    npi: str,
    date_naissance: date,
    concours: Concours,
    centre: Centre,
    maintenant: datetime | None = None,
) -> ResultatInscription:
    # Étape 2 — clôture
    if est_cloture(concours, maintenant):
        raise InscriptionRefusee("CLOTURE", "Inscriptions closes.", 403)

    # Étape 3 — âge
    if age_au_31_decembre(date_naissance, concours.date_epreuve.year) > AGE_MAX:
        raise InscriptionRefusee(
            "AGE", f"Le candidat aura plus de {AGE_MAX} ans au 31 décembre "
                   f"{concours.date_epreuve.year}."
        )

    # Étape 4 (pré-contrôle) — message clair, évite d'appeler le service pour
    # un double clic. La garantie est l'index unique, plus bas.
    existante = _inscription_active_du_jour(npi, concours)
    if existante:
        return _rejouer_ou_refuser(existante, concours, centre)

    # Étape 5 (pré-contrôle) — inutile d'appeler le service si le centre est plein.
    if not Centre.objects.filter(pk=centre.pk, inscrits__lt=F("capacite")).exists():
        raise InscriptionRefusee("CENTRE_COMPLET", "Le centre d'examen est complet.", 409)

    # Étape 7 — identification, HORS transaction, 5 s au plus.
    identite = verifier_identite(npi)
    if identite.statut == StatutIdentite.INCONNU:
        raise InscriptionRefusee("NPI_INCONNU", "NPI inconnu du service d'identification.")
    statut = (
        Inscription.Statut.VALIDEE
        if identite.statut == StatutIdentite.TROUVE
        else Inscription.Statut.EN_ATTENTE
    )

    try:
        with transaction.atomic():
            # Étapes 5 + 6 — réserve une place et un numéro en une instruction.
            reserve = Centre.objects.filter(
                pk=centre.pk, inscrits__lt=F("capacite")
            ).update(
                inscrits=F("inscrits") + 1,
                dernier_numero=F("dernier_numero") + 1,
            )
            if not reserve:
                raise InscriptionRefusee(
                    "CENTRE_COMPLET", "Le centre d'examen est complet.", 409
                )
            # La ligne est verrouillée par notre UPDATE : cette lecture voit
            # notre propre valeur, aucune autre transaction ne peut la changer.
            n = Centre.objects.values_list("dernier_numero", flat=True).get(pk=centre.pk)
            numero = f"{centre.code}-{n:04d}"

            # Étape 8 — candidat (conservé d'une campagne à l'autre), puis inscription.
            candidat, cree = Candidat.objects.get_or_create(
                npi=npi,
                defaults={
                    "nom": identite.nom,
                    "prenoms": identite.prenoms,
                    "date_naissance": date_naissance,
                },
            )
            if not cree and identite.statut == StatutIdentite.TROUVE and (
                candidat.nom != identite.nom or candidat.prenoms != identite.prenoms
            ):
                candidat.nom, candidat.prenoms = identite.nom, identite.prenoms
                candidat.save(update_fields=["nom", "prenoms"])

            inscription = Inscription.objects.create(
                concours=concours,
                centre=centre,
                npi=npi,
                date_epreuve=concours.date_epreuve,
                numero_table=numero,
                statut=statut,
            )
    except IntegrityError:
        # Une requête simultanée du même candidat a gagné (index unique
        # npi + jour). Notre transaction est annulée, compteur compris.
        existante = _inscription_active_du_jour(npi, concours)
        if existante:
            return _rejouer_ou_refuser(existante, concours, centre)
        raise

    return ResultatInscription(inscription, creee=True)
