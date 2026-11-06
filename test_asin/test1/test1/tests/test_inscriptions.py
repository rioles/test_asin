import threading
import time
from collections import Counter
from datetime import date, datetime, timezone as dt_tz
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from test1.models import Candidat, Centre, Concours, Inscription
from test1.services import identite_client
from test1.services.identite_client import ResultatIdentite, StatutIdentite
from test1.services.inscription_service import (
    InscriptionRefusee,
    age_au_31_decembre,
    est_cloture,
    inscrire,
)

PATCH_IDENTITE = "test1.services.inscription_service.verifier_identite"
TROUVE = ResultatIdentite(StatutIdentite.TROUVE, "DOSSOU", "Koffi")
NAISSANCE_OK = date(1995, 3, 1)
OUVERT = datetime(2026, 11, 1, 12, 0, tzinfo=dt_tz.utc)


def creer_donnees(capacite_p=10):
    jour = date(2026, 12, 12)
    douanes = Concours.objects.create(
        code="DOUANES", libelle="Douanes", date_epreuve=jour,
        cloture=datetime(2026, 11, 25, 22, 59, tzinfo=dt_tz.utc))
    impots = Concours.objects.create(
        code="IMPOTS", libelle="Impôts", date_epreuve=jour,
        cloture=datetime(2026, 11, 25, 22, 59, tzinfo=dt_tz.utc))
    # 23 h 59 heure du Bénin = 22 h 59 UTC
    tresor = Concours.objects.create(
        code="TRESOR", libelle="Trésor", date_epreuve=date(2026, 12, 19),
        cloture=datetime(2026, 11, 20, 22, 59, tzinfo=dt_tz.utc))
    p = Centre.objects.create(code="P", nom="Parakou", capacite=capacite_p)
    c = Centre.objects.create(code="C", nom="Cotonou", capacite=5000)
    return douanes, impots, tresor, p, c


# ---------------------------------------------------------------------------
# Règles d'âge et de clôture (INC-205, INC-204)
# ---------------------------------------------------------------------------
class RegleAgeTests(SimpleTestCase):
    def test_inc205_ne_le_20_juin_1991_a_35_ans_donc_accepte(self):
        self.assertEqual(age_au_31_decembre(date(1991, 6, 20), 2026), 35)

    def test_bornes(self):
        self.assertEqual(age_au_31_decembre(date(1991, 1, 1), 2026), 35)
        self.assertEqual(age_au_31_decembre(date(1991, 12, 31), 2026), 35)
        self.assertEqual(age_au_31_decembre(date(1990, 12, 31), 2026), 36)
        self.assertEqual(age_au_31_decembre(date(1992, 2, 29), 2026), 34)


class RegleClotureTests(SimpleTestCase):
    def setUp(self):
        # Trésor : clôture le 20/11/2026 à 23 h 59 heure du Bénin
        self.c = Concours(code="TRESOR", libelle="Trésor", date_epreuve=date(2026, 12, 19),
                          cloture=datetime(2026, 11, 20, 22, 59, tzinfo=dt_tz.utc))

    def test_inc204_ouvert_a_23h_heure_du_benin(self):
        a_23h_benin = datetime(2026, 11, 20, 22, 0, tzinfo=dt_tz.utc)
        self.assertFalse(est_cloture(self.c, a_23h_benin))

    def test_ouvert_a_la_minute_de_cloture_puis_ferme(self):
        self.assertFalse(est_cloture(self.c, datetime(2026, 11, 20, 22, 59, tzinfo=dt_tz.utc)))
        self.assertTrue(est_cloture(self.c, datetime(2026, 11, 20, 22, 59, 1, tzinfo=dt_tz.utc)))

    @override_settings(TIME_ZONE="Africa/Porto-Novo")
    def test_independant_du_fuseau_du_serveur(self):
        from zoneinfo import ZoneInfo
        a_23h30_benin = datetime(2026, 11, 20, 23, 30, tzinfo=ZoneInfo("Africa/Porto-Novo"))
        self.assertFalse(est_cloture(self.c, a_23h30_benin))

    def test_valeur_sans_fuseau_lue_comme_utc(self):
        self.c.cloture = datetime(2026, 11, 20, 22, 59)
        self.assertFalse(est_cloture(self.c, datetime(2026, 11, 20, 22, 30, tzinfo=dt_tz.utc)))


# ---------------------------------------------------------------------------
# Inscription (étapes 4 à 8)
# ---------------------------------------------------------------------------
@mock.patch(PATCH_IDENTITE, return_value=TROUVE)
class InscriptionTests(TestCase):
    def setUp(self):
        self.douanes, self.impots, self.tresor, self.p, self.c = creer_donnees()

    def test_numero_de_table_au_format_P_0001(self, _):
        r = inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        self.assertTrue(r.creee)
        self.assertEqual(r.inscription.numero_table, "P-0001")
        self.assertEqual(r.inscription.statut, Inscription.Statut.VALIDEE)
        cand = Candidat.objects.get(npi="1000000001")
        self.assertEqual((cand.nom, cand.prenoms), ("DOSSOU", "Koffi"))

    def test_numero_unique_dans_le_centre_tous_concours_confondus(self, _):
        a = inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        b = inscrire("1000000002", NAISSANCE_OK, self.tresor, self.p, OUVERT)
        self.assertEqual([a.inscription.numero_table, b.inscription.numero_table],
                         ["P-0001", "P-0002"])

    def test_inc203_double_clic_rejoue_la_meme_inscription(self, ident):
        a = inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        b = inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        self.assertFalse(b.creee)
        self.assertEqual(a.inscription.pk, b.inscription.pk)
        self.assertEqual(Inscription.objects.count(), 1)
        self.assertEqual(ident.call_count, 1)  # pas de second appel au service
        self.p.refresh_from_db()
        self.assertEqual(self.p.inscrits, 1)

    def test_meme_concours_autre_centre_refuse(self, _):
        inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        with self.assertRaises(InscriptionRefusee) as e:
            inscrire("1000000001", NAISSANCE_OK, self.douanes, self.c, OUVERT)
        self.assertEqual(e.exception.code, "DEJA_INSCRIT")

    def test_inc208_concours_du_meme_jour_refuse_conformement_a_la_regle(self, _):
        inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        with self.assertRaises(InscriptionRefusee) as e:
            inscrire("1000000001", NAISSANCE_OK, self.impots, self.p, OUVERT)
        self.assertEqual(e.exception.code, "MEME_JOUR")

    def test_capacite_tous_concours_confondus(self, _):
        self.p.capacite = 2
        self.p.save()
        inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        inscrire("1000000002", NAISSANCE_OK, self.tresor, self.p, OUVERT)
        with self.assertRaises(InscriptionRefusee) as e:
            inscrire("1000000003", NAISSANCE_OK, self.impots, self.p, OUVERT)
        self.assertEqual(e.exception.code, "CENTRE_COMPLET")

    def test_inc205_ne_en_juin_1991_accepte(self, _):
        r = inscrire("1000000001", date(1991, 6, 20), self.douanes, self.p, OUVERT)
        self.assertTrue(r.creee)

    def test_36_ans_refuse(self, _):
        with self.assertRaises(InscriptionRefusee) as e:
            inscrire("1000000001", date(1990, 12, 31), self.douanes, self.p, OUVERT)
        self.assertEqual(e.exception.code, "AGE")

    def test_inc204_inscription_acceptee_a_23h_heure_du_benin(self, _):
        r = inscrire("1000000001", NAISSANCE_OK, self.tresor, self.p,
                     datetime(2026, 11, 20, 22, 0, tzinfo=dt_tz.utc))
        self.assertTrue(r.creee)
        with self.assertRaises(InscriptionRefusee) as e:
            inscrire("1000000002", NAISSANCE_OK, self.tresor, self.p,
                     datetime(2026, 11, 20, 23, 0, tzinfo=dt_tz.utc))
        self.assertEqual(e.exception.code, "CLOTURE")

    def test_npi_inconnu_refuse_sans_consommer_de_place(self, ident):
        ident.return_value = ResultatIdentite(StatutIdentite.INCONNU)
        with self.assertRaises(InscriptionRefusee) as e:
            inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        self.assertEqual(e.exception.code, "NPI_INCONNU")
        self.p.refresh_from_db()
        self.assertEqual((self.p.inscrits, self.p.dernier_numero), (0, 0))

    def test_service_indisponible_inscription_en_attente(self, ident):
        ident.return_value = ResultatIdentite(StatutIdentite.INDISPONIBLE)
        r = inscrire("1000000001", NAISSANCE_OK, self.douanes, self.p, OUVERT)
        self.assertEqual(r.inscription.statut, Inscription.Statut.EN_ATTENTE)
        self.assertEqual(r.inscription.numero_table, "P-0001")


# ---------------------------------------------------------------------------
# API HTTP
# ---------------------------------------------------------------------------
@mock.patch(PATCH_IDENTITE, return_value=TROUVE)
@mock.patch("test1.services.inscription_service.timezone.now", return_value=OUVERT)
class ApiTests(TestCase):
    def setUp(self):
        self.douanes, *_ = creer_donnees()
        self.client = APIClient()

    def corps(self, npi="1000000001"):
        return {"npi": npi, "date_naissance": "1995-03-01",
                "concours": "DOUANES", "centre": "P"}

    def test_post_201_puis_200_au_second_clic(self, *_):
        r1 = self.client.post("/api/inscriptions", self.corps(), format="json")
        r2 = self.client.post("/api/inscriptions", self.corps(), format="json")
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(r1.data["numero_table"], "P-0001")

    def test_forme_invalide_400(self, *_):
        r = self.client.post("/api/inscriptions", self.corps(npi="12AB"), format="json")
        self.assertEqual(r.status_code, 400)

    def test_convocation_ne_rappelle_pas_le_service(self, _now, ident):
        r = self.client.post("/api/inscriptions", self.corps(), format="json")
        ident.reset_mock()
        conv = self.client.get(f"/api/inscriptions/{r.data['id']}/convocation")
        self.assertEqual(conv.status_code, 200)
        self.assertEqual(conv.data["nom"], "DOSSOU")
        ident.assert_not_called()

    def test_liste_des_inscrits_nombre_de_requetes_constant(self, *_):
        Centre.objects.filter(code="P").update(capacite=100)
        for i in range(30):
            self.client.post("/api/inscriptions", self.corps(f"20000000{i:02d}"), format="json")
        with self.assertNumQueries(3):  # centre + inscriptions + candidats
            r = self.client.get("/api/centres/P/inscrits?concours=DOUANES")
        self.assertEqual(r.data["total"], 30)
        self.assertEqual(r.data["inscrits"][0]["nom"], "DOSSOU")


# ---------------------------------------------------------------------------
# Service d'identification : jamais plus de 5 s (INC-206)
# ---------------------------------------------------------------------------
class _ServiceLent(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/lent"):
            time.sleep(8)
        if self.path.endswith("/goutte"):  # répond octet par octet pendant 8 s
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            for ch in '{"nom": "A", "prenoms": "B"}'.ljust(32):
                self.wfile.write(ch.encode())
                self.wfile.flush()
                time.sleep(0.25)
            return
        if self.path.endswith("/0000000000"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"nom": "DOSSOU", "prenoms": "Koffi"}')

    def log_message(self, *args):
        pass


class IdentiteClientTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), _ServiceLent)
        cls.serveur.daemon_threads = True
        cls.serveur.handle_error = lambda *a: None  # client parti à 5 s : attendu
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.serveur.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()
        cls.serveur.server_close()
        super().tearDownClass()

    def appeler(self, npi):
        with override_settings(IDENTITE_BASE_URL=self.url, IDENTITE_DELAI_S=5.0):
            debut = time.monotonic()
            res = identite_client.verifier_identite(npi)
            return res, time.monotonic() - debut

    def test_reponse_normale(self):
        res, _ = self.appeler("1000000001")
        self.assertEqual(res, ResultatIdentite(StatutIdentite.TROUVE, "DOSSOU", "Koffi"))

    def test_npi_inconnu(self):
        res, _ = self.appeler("0000000000")
        self.assertEqual(res.statut, StatutIdentite.INCONNU)

    def test_service_qui_ne_repond_pas_coupe_a_5_secondes(self):
        res, duree = self.appeler("lent")
        self.assertEqual(res.statut, StatutIdentite.INDISPONIBLE)
        self.assertLess(duree, 5.5)

    def test_reponse_au_compte_gouttes_coupee_a_5_secondes(self):
        res, duree = self.appeler("goutte")
        self.assertEqual(res.statut, StatutIdentite.INDISPONIBLE)
        self.assertLess(duree, 5.5)

    def test_service_arrete(self):
        with override_settings(IDENTITE_BASE_URL="http://127.0.0.1:1"):
            res = identite_client.verifier_identite("1000000001")
        self.assertEqual(res.statut, StatutIdentite.INDISPONIBLE)


# ---------------------------------------------------------------------------
# Requêtes simultanées (INC-201, INC-202, INC-203)
# ---------------------------------------------------------------------------
def identite_lente(npi):
    time.sleep(0.05)  # élargit la fenêtre de concurrence
    return TROUVE


@mock.patch(PATCH_IDENTITE, side_effect=identite_lente)
class ConcurrenceTests(TransactionTestCase):
    def setUp(self):
        self.douanes, self.impots, self.tresor, self.p, _ = creer_donnees(capacite_p=20)

    def lancer(self, demandes):
        """Exécute toutes les demandes en même temps (une connexion par thread)."""
        depart = threading.Barrier(len(demandes))
        resultats = [None] * len(demandes)

        def travail(i, npi, concours):
            try:
                depart.wait()
                resultats[i] = inscrire(npi, NAISSANCE_OK, concours, self.p, OUVERT)
            except InscriptionRefusee as e:
                resultats[i] = e.code
            except Exception as e:  # noqa: BLE001 — toute autre erreur fait échouer le test
                resultats[i] = e
            finally:
                connection.close()

        threads = [threading.Thread(target=travail, args=(i, *d)) for i, d in enumerate(demandes)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        erreurs = [r for r in resultats if isinstance(r, Exception) and not isinstance(r, str)]
        self.assertEqual(erreurs, [])
        return resultats

    def test_40_candidats_simultanes_pour_20_places(self, _):
        demandes = [(f"30000000{i:02d}", self.douanes if i % 2 else self.tresor)
                    for i in range(40)]
        res = self.lancer(demandes)

        acceptes = [r for r in res if not isinstance(r, str)]
        self.assertEqual(len(acceptes), 20)
        self.assertEqual(Counter(r for r in res if isinstance(r, str)), {"CENTRE_COMPLET": 20})

        numeros = list(Inscription.objects.filter(centre=self.p)
                       .values_list("numero_table", flat=True))
        self.assertEqual(len(numeros), 20)
        self.assertEqual(sorted(numeros), [f"P-{n:04d}" for n in range(1, 21)])  # aucun doublon
        self.p.refresh_from_db()
        self.assertEqual(self.p.inscrits, 20)

    def test_meme_candidat_10_clics_simultanes(self, _):
        res = self.lancer([("4000000001", self.douanes)] * 10)
        self.assertEqual(Inscription.objects.filter(npi="4000000001").count(), 1)
        self.assertEqual(sum(1 for r in res if r.creee), 1)
        self.assertEqual({r.inscription.pk for r in res}, {Inscription.objects.get().pk})
        self.p.refresh_from_db()
        self.assertEqual((self.p.inscrits, self.p.dernier_numero), (1, 1))

    def test_meme_candidat_deux_concours_du_meme_jour_simultanes(self, _):
        res = self.lancer([("5000000001", self.douanes), ("5000000001", self.impots)] * 5)
        self.assertEqual(Inscription.objects.filter(npi="5000000001").count(), 1)
        self.assertIn("MEME_JOUR", res)
        self.p.refresh_from_db()
        self.assertEqual(self.p.inscrits, 1)
