from django.db import models
from django.db.models import Q


class Inscription(models.Model):
    class Statut(models.TextChoices):
        VALIDEE = "VALIDEE", "Validée"
        # Le service d'identification n'a pas répondu à temps (règle des 5 s)
        EN_ATTENTE = "EN_ATTENTE_VERIFICATION", "En attente de vérification"
        ANNULEE = "ANNULEE", "Annulée"

    concours = models.ForeignKey(
        "Concours", on_delete=models.PROTECT, related_name="inscriptions"
    )
    centre = models.ForeignKey(
        "Centre", on_delete=models.PROTECT, related_name="inscriptions"
    )
    npi = models.CharField(max_length=10)
    # Copie de concours.date_epreuve : permet à PostgreSQL d'interdire, par un
    # index unique, deux inscriptions du même NPI le même jour (INC-203, règle
    # « pas deux concours le même jour »), même avec des requêtes simultanées.
    date_epreuve = models.DateField()
    numero_table = models.CharField(max_length=20)
    statut = models.CharField(
        max_length=30, choices=Statut.choices, default=Statut.VALIDEE
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscriptions"
        constraints = [
            # INC-203 + règle du même jour : un seul concours actif par NPI et par jour
            # (couvre aussi « une seule inscription par concours »).
            models.UniqueConstraint(
                fields=["npi", "date_epreuve"],
                condition=~Q(statut="ANNULEE"),
                name="uniq_insc_npi_jour",
            ),
            # INC-201 : numéro de table unique dans le centre, tous concours confondus.
            models.UniqueConstraint(
                fields=["centre", "numero_table"],
                name="uniq_insc_centre_numero",
            ),
            models.CheckConstraint(
                condition=Q(statut__in=["VALIDEE", "EN_ATTENTE_VERIFICATION", "ANNULEE"]),
                name="inscriptions_statut_valide",
            ),
        ]
        indexes = [
            # INC-207 : liste des inscrits d'un centre pour un concours, triée par numéro
            models.Index(
                fields=["centre", "concours", "numero_table"],
                name="idx_insc_centre_concours",
            ),
            models.Index(fields=["npi"], name="idx_inscriptions_npi"),
        ]

    def __str__(self):
        return f"{self.numero_table} — {self.npi} ({self.concours_id})"
