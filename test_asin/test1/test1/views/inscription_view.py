from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Candidat, Centre, Inscription
from ..serializers import InscriptionCreateSerializer, InscriptionSerializer
from ..services.inscription_service import InscriptionRefusee, inscrire


class InscriptionCreateView(APIView):
    """POST /api/inscriptions"""

    def post(self, request):
        # Étape 1 — contrôle de forme (400)
        ser = InscriptionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            res = inscrire(d["npi"], d["date_naissance"], d["concours"], d["centre"])
        except InscriptionRefusee as e:
            return Response({"code": e.code, "detail": e.message}, status=e.http_status)
        return Response(
            InscriptionSerializer(res.inscription).data,
            status=status.HTTP_201_CREATED if res.creee else status.HTTP_200_OK,
        )


class ConvocationView(APIView):
    """GET /api/inscriptions/{id}/convocation

    INC-206 : ne rappelle plus le service d'identification. Les nom et prénoms
    viennent de `candidats`, enregistrés à l'inscription. Une lenteur du
    service ne bloque donc plus les convocations.
    """

    def get(self, request, pk):
        insc = get_object_or_404(
            Inscription.objects.select_related("concours", "centre"), pk=pk
        )
        cand = Candidat.objects.filter(npi=insc.npi).only("nom", "prenoms").first()
        return Response({
            "numero_table": insc.numero_table,
            "npi": insc.npi,
            "nom": cand.nom if cand else "",
            "prenoms": cand.prenoms if cand else "",
            "concours": insc.concours.libelle,
            "date_epreuve": insc.date_epreuve,
            "centre": insc.centre.nom,
            "statut": insc.statut,
        })


class InscritsCentreView(APIView):
    """GET /api/centres/{code}/inscrits?concours=…

    INC-207 : avant, une requête par inscrit vers `candidats`, sans index sur
    npi (5 000 inscrits = 5 001 requêtes et autant de parcours de table).
    Maintenant : 2 requêtes indexées, quel que soit le nombre d'inscrits.
    """

    def get(self, request, code):
        centre = get_object_or_404(Centre, code=code)
        concours = request.query_params.get("concours")
        if not concours:
            return Response({"detail": "Paramètre concours obligatoire."}, status=400)

        inscrits = list(
            Inscription.objects.filter(centre=centre, concours__code=concours)
            .exclude(statut=Inscription.Statut.ANNULEE)
            .order_by("numero_table")
            .values("id", "numero_table", "npi", "statut")
        )
        noms = {
            c["npi"]: c
            for c in Candidat.objects.filter(npi__in=[i["npi"] for i in inscrits])
            .values("npi", "nom", "prenoms")
        }
        for i in inscrits:
            c = noms.get(i["npi"], {})
            i["nom"], i["prenoms"] = c.get("nom", ""), c.get("prenoms", "")
        return Response({"centre": centre.code, "concours": concours,
                         "total": len(inscrits), "inscrits": inscrits})


class RechercheInscritsView(APIView):
    """GET /api/inscrits/recherche?nom=…  (50 résultats au plus)

    `candidats` conserve les campagnes précédentes : on ne renvoie que les
    candidats ayant une inscription active.
    """

    def get(self, request):
        nom = (request.query_params.get("nom") or "").strip()
        if len(nom) < 2:
            return Response({"detail": "Indiquez au moins 2 caractères."}, status=400)
        inscrit = Inscription.objects.filter(npi=OuterRef("npi")).exclude(
            statut=Inscription.Statut.ANNULEE
        )
        resultats = (
            Candidat.objects.filter(Exists(inscrit), nom__istartswith=nom)
            .order_by("nom", "prenoms")
            .values("npi", "nom", "prenoms")[:50]
        )
        return Response(list(resultats))
