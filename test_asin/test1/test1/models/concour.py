from django.db import models
from django.db.models import Q, F


class Concours(models.Model):
    code = models.CharField(max_length=10, unique=True)
    libelle = models.CharField(max_length=100)
    date_epreuve = models.DateField()
    # CORRECTION INC-204 : DateTimeField = TIMESTAMPTZ en PostgreSQL
    cloture = models.DateTimeField()

    class Meta:
        db_table = "concours"
        verbose_name = "Concours"
        verbose_name_plural = "Concours"

    def __str__(self):
        return f"{self.code} — {self.libelle}"