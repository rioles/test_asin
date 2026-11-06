"""
Charge les concours et centres de démonstration (rejouable sans risque).

    ..\\venv\\Scripts\\python.exe manage.py donnees_demo

Lokossa n'a que 3 places, pour voir le refus « centre complet » avec quelques curls.
Les compteurs des centres sont recalculés à partir des inscriptions existantes.
"""
from datetime import date, datetime, timezone

from django.core.management.base import BaseCommand
from django.db.models import Count

from test1.models import Centre, Concours, Inscription

CONCOURS = [
    # clôture en UTC : 22:59 UTC = 23:59 heure du Bénin
    ("DOUANES", "Concours des inspecteurs des douanes", date(2026, 12, 12), datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc)),
    ("IMPOTS", "Concours des contrôleurs des impôts", date(2026, 12, 12), datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc)),
    ("TRESOR", "Concours des agents du Trésor public", date(2026, 12, 19), datetime(2026, 11, 20, 22, 59, tzinfo=timezone.utc)),
]
CENTRES = [("C", "Cotonou", 6000), ("P", "Parakou", 700), ("L", "Lokossa", 3),
           ("N", "Porto-Novo", 800), ("A", "Abomey", 600)]


class Command(BaseCommand):
    help = "Charge les concours et centres de démonstration."

    def handle(self, *args, **options):
        for code, libelle, jour, cloture in CONCOURS:
            Concours.objects.update_or_create(
                code=code, defaults={"libelle": libelle, "date_epreuve": jour, "cloture": cloture})
        for code, nom, capacite in CENTRES:
            centre, _ = Centre.objects.get_or_create(code=code, defaults={"nom": nom, "capacite": capacite})
            nb = Inscription.objects.filter(centre=centre).exclude(statut="ANNULEE").count()
            centre.nom, centre.capacite, centre.inscrits = nom, max(capacite, nb), nb
            numeros = Inscription.objects.filter(centre=centre).values_list("numero_table", flat=True)
            centre.dernier_numero = max([centre.dernier_numero] + [int(n[2:]) for n in numeros])
            centre.save()
        for c in Centre.objects.annotate(n=Count("inscriptions")).order_by("code"):
            self.stdout.write(f"  centre {c.code} {c.nom:<11} {c.inscrits}/{c.capacite}")
        for c in Concours.objects.order_by("code"):
            self.stdout.write(f"  concours {c.code:<8} épreuve {c.date_epreuve}  clôture {c.cloture:%Y-%m-%d %H:%M} UTC")
        self.stdout.write(self.style.SUCCESS("Données de démonstration prêtes."))
