from django.db import models

class Candidat(models.Model):
    # CORRECTION INC-203 : un NPI ne peut exister qu'une fois
    npi = models.CharField(max_length=10, unique=True)
    # Vides tant que l'identité n'a pas pu être vérifiée (inscription « en attente »)
    nom = models.CharField(max_length=60, blank=True, default="")
    prenoms = models.CharField(max_length=80, blank=True, default="")
    date_naissance = models.DateField()
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "candidats"
        indexes = [
            # CORRECTION INC-205 : accélère l'audit d'âge
            models.Index(fields=["date_naissance"], name="idx_candidats_date_naissance"),
            models.Index(fields=["nom"], name="idx_candidats_nom"),
        ]

    def __str__(self):
        return f"{self.npi} — {self.nom} {self.prenoms}"