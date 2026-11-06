from rest_framework import serializers

from datetime import date

from django.utils import timezone


from .models import Concours, Centre, Candidat, Inscription




# inscriptions/serializers.py
"""
Serializers DRF pour l'application « Inscriptions aux concours ».

Rôle :
  - valider la FORME de la requête (étape 1 du dossier technique)
  - NE PAS appliquer les règles métier (âge, clôture, capacité...)
    → ces règles sont dans inscription_service.py, dans la transaction
"""




# ---------------------------------------------------------------------------
# Entrée — POST /api/inscriptions
# ---------------------------------------------------------------------------
class InscriptionCreateSerializer(serializers.Serializer):
    """
    Valide uniquement la FORME (étape 1).
    Les règles métier (clôture, âge, capacité, doublon) sont dans le service.
    """
    npi = serializers.CharField(
        min_length=10, max_length=10,
        error_messages={
            "min_length": "Le NPI doit comporter exactement 10 chiffres.",
            "max_length": "Le NPI doit comporter exactement 10 chiffres.",
        },
    )
    date_naissance = serializers.DateField()
    concours = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Concours.objects.all(),
        error_messages={"does_not_exist": "Concours inconnu."},
    )
    centre = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Centre.objects.all(),
        error_messages={"does_not_exist": "Centre inconnu."},
    )

    def validate_npi(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError(
                "Le NPI doit comporter exactement 10 chiffres."
            )
        return value

    def validate_date_naissance(self, value: date) -> date:
        if value > timezone.localdate():
            raise serializers.ValidationError(
                "La date de naissance ne peut pas être dans le futur."
            )
        return value


# ---------------------------------------------------------------------------
# Sortie — réponse 201
# ---------------------------------------------------------------------------
class InscriptionSerializer(serializers.ModelSerializer):
    concours = serializers.SlugRelatedField(slug_field="code", read_only=True)
    centre = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = Inscription
        fields = (
            "id", "numero_table", "npi",
            "concours", "centre", "date_epreuve", "statut", "cree_le",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Candidat (lecture)
# ---------------------------------------------------------------------------
class CandidatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidat
        fields = ("npi", "nom", "prenoms", "date_naissance")


# ---------------------------------------------------------------------------
# Concours / Centre (lecture)
# ---------------------------------------------------------------------------
class ConcoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = Concours
        fields = ("code", "libelle", "date_epreuve", "cloture")


class CentreSerializer(serializers.ModelSerializer):
    places_restantes = serializers.SerializerMethodField()

    class Meta:
        model = Centre
        fields = ("code", "nom", "capacite", "inscrits", "places_restantes")

    def get_places_restantes(self, obj):
        return max(0, obj.capacite - obj.inscrits)