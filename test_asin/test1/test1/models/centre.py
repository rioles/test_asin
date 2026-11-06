from django.db import models
from django.db.models import F, Q


class Centre(models.Model):
    code = models.CharField(max_length=1, unique=True)
    nom = models.CharField(max_length=50)
    capacite = models.IntegerField()
    # CORRECTION INC-202 : compteur atomique, plus fiable qu'un COUNT(*) à chaque requête
    inscrits = models.IntegerField(default=0)
    # INC-201 : dernier numéro de table attribué dans le centre. Incrémenté dans le
    # même UPDATE atomique que `inscrits` ; ne redescend jamais (pas de réemploi
    # d'un numéro même après une annulation).
    dernier_numero = models.IntegerField(default=0)

    class Meta:
        db_table = "centres"
        constraints = [
            models.CheckConstraint(
                condition=Q(inscrits__gte=0),
                name="centres_inscrits_positif",
            ),
            models.CheckConstraint(
                condition=Q(inscrits__lte=F("capacite")),
                name="centres_capacite_respectee",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.nom} ({self.inscrits}/{self.capacite})"