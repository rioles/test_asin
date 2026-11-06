"""
Tests d'intégration de bout en bout.

Rien n'est simulé dans l'application : un vrai serveur Django (LiveServerTestCase),
de vraies requêtes HTTP, PostgreSQL, et un faux service national d'identification
qui est lui aussi un vrai serveur HTTP :
  * NPI commençant par 9 → le service met 8 s à répondre (lenteur du 19/11) ;
  * NPI 0000000000      → 404 (NPI inconnu) ;
  * autres NPI          → 200 en 50 ms.
"""
import json
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone as dt_tz
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.test import LiveServerTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from test1.models import Candidat, Centre, Concours, Inscription


class _FauxServiceIdentite(BaseHTTPRequestHandler):
    def do_GET(self):
        npi = self.path.rsplit("/", 1)[-1]
        if npi.startswith("9"):
            time.sleep(8)
        else:
            time.sleep(0.05)
        if npi == "0000000000":
            self.send_response(404)
            self.end_headers()
            return
        corps = json.dumps({"npi": npi, "nom": "DOSSOU", "prenoms": f"Koffi {npi[-3:]}"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *args):
        pass


def creer_referentiel(capacite_p):
    ouvert = datetime(2099, 1, 1, tzinfo=dt_tz.utc)  # clôture lointaine
    Concours.objects.create(code="DOUANES", libelle="Douanes", date_epreuve=date(2026, 12, 12), cloture=ouvert)
    Concours.objects.create(code="IMPOTS", libelle="Impôts", date_epreuve=date(2026, 12, 12), cloture=ouvert)
    Concours.objects.create(code="TRESOR", libelle="Trésor", date_epreuve=date(2026, 12, 19), cloture=ouvert)
    Centre.objects.create(code="P", nom="Parakou", capacite=capacite_p)
    Centre.objects.create(code="C", nom="Cotonou", capacite=6000)


class _ServeurSilencieux(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # le client a abandonné (coupure à 5 s) : attendu, pas une erreur


class InscriptionHttpTests(LiveServerTestCase):
    """Le vrai serveur reçoit de vraies requêtes HTTP, en même temps."""

    # Sous Windows, « localhost » essaie d'abord IPv6 et perd environ 2 s par connexion.
    host = "127.0.0.1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.identite = _ServeurSilencieux(("127.0.0.1", 0), _FauxServiceIdentite)
        threading.Thread(target=cls.identite.serve_forever, daemon=True).start()
        cls._reglages = override_settings(
            IDENTITE_BASE_URL=f"http://127.0.0.1:{cls.identite.server_port}")
        cls._reglages.enable()

    @classmethod
    def tearDownClass(cls):
        cls._reglages.disable()
        cls.identite.shutdown()
        cls.identite.server_close()
        super().tearDownClass()

    def setUp(self):
        creer_referentiel(capacite_p=10)

    def appeler(self, methode, chemin, corps=None):
        req = urllib.request.Request(
            self.live_server_url + chemin, method=methode,
            data=json.dumps(corps).encode() if corps is not None else None,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def poster_en_meme_temps(self, corps_list):
        depart = threading.Barrier(len(corps_list))
        resultats = [None] * len(corps_list)

        def envoyer(i, corps):
            depart.wait()
            resultats[i] = self.appeler("POST", "/api/inscriptions", corps)

        threads = [threading.Thread(target=envoyer, args=(i, c)) for i, c in enumerate(corps_list)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        return resultats

    @staticmethod
    def corps(npi, concours="DOUANES", centre="P"):
        return {"npi": npi, "date_naissance": "1995-03-01", "concours": concours, "centre": centre}

    def test_30_requetes_http_simultanees_pour_10_places(self):
        res = self.poster_en_meme_temps([self.corps(f"10000000{i:02d}") for i in range(30)])
        codes = Counter(code for code, _ in res)
        self.assertEqual(codes, {201: 10, 409: 20})
        self.assertTrue(all(b["code"] == "CENTRE_COMPLET" for c, b in res if c == 409))
        numeros = sorted(b["numero_table"] for c, b in res if c == 201)
        self.assertEqual(numeros, [f"P-{n:04d}" for n in range(1, 11)])
        self.assertEqual(Inscription.objects.filter(centre__code="P").count(), 10)
        self.assertEqual(Centre.objects.get(code="P").inscrits, 10)

    def test_double_clic_http_simultane_une_seule_inscription(self):
        res = self.poster_en_meme_temps([self.corps("2000000001")] * 8)
        self.assertEqual(Counter(c for c, _ in res), {201: 1, 200: 7})
        self.assertEqual(len({b["id"] for _, b in res}), 1)
        self.assertEqual(Inscription.objects.filter(npi="2000000001").count(), 1)

    def test_deux_concours_du_meme_jour_en_meme_temps(self):
        res = self.poster_en_meme_temps([self.corps("2000000002", "DOUANES"),
                                         self.corps("2000000002", "IMPOTS")] * 3)
        self.assertEqual(Inscription.objects.filter(npi="2000000002").count(), 1)
        self.assertIn("MEME_JOUR", {b.get("code") for c, b in res if c == 409})

    def test_service_lent_inscription_en_attente_en_moins_de_6_s(self):
        debut = time.monotonic()
        code, corps = self.appeler("POST", "/api/inscriptions", self.corps("9000000001"))
        duree = time.monotonic() - debut
        self.assertEqual(code, 201)
        self.assertEqual(corps["statut"], "EN_ATTENTE_VERIFICATION")
        self.assertLess(duree, 6.0)

    def test_service_lent_ne_bloque_ni_les_autres_ni_les_convocations(self):
        code, inscrit = self.appeler("POST", "/api/inscriptions", self.corps("1000000099"))
        self.assertEqual(code, 201)
        lents = []
        en_cours = threading.Thread(target=lambda: lents.extend(
            self.poster_en_meme_temps([self.corps(f"90000000{i:02d}", centre="C") for i in range(5)])))
        en_cours.start()
        time.sleep(1.0)  # les 5 inscriptions attendent maintenant le service lent
        self.assertTrue(en_cours.is_alive())
        debut = time.monotonic()
        code, conv = self.appeler("GET", f"/api/inscriptions/{inscrit['id']}/convocation")
        duree_convocation = time.monotonic() - debut
        code_autre, _ = self.appeler("POST", "/api/inscriptions", self.corps("1000000098", centre="C"))
        self.assertTrue(en_cours.is_alive(), "les inscriptions lentes devaient encore attendre")
        en_cours.join(30)
        self.assertEqual((code, conv["nom"]), (200, "DOSSOU"))
        self.assertLess(duree_convocation, 1.0)
        self.assertEqual(code_autre, 201)  # une inscription au service rapide passe pendant l'attente
        self.assertEqual(len(lents), 5)
        self.assertTrue(all(c == 201 and b["statut"] == "EN_ATTENTE_VERIFICATION" for c, b in lents))

    def test_npi_inconnu_refuse(self):
        code, corps = self.appeler("POST", "/api/inscriptions", self.corps("0000000000"))
        self.assertEqual((code, corps["code"]), (422, "NPI_INCONNU"))
        self.assertEqual(Centre.objects.get(code="P").inscrits, 0)

    def test_parcours_complet_inscription_convocation_liste(self):
        code, ins = self.appeler("POST", "/api/inscriptions", self.corps("1000000123"))
        self.assertEqual((code, ins["numero_table"], ins["statut"]), (201, "P-0001", "VALIDEE"))
        code, conv = self.appeler("GET", f"/api/inscriptions/{ins['id']}/convocation")
        self.assertEqual((code, conv["numero_table"], conv["prenoms"]), (200, "P-0001", "Koffi 123"))
        code, liste = self.appeler("GET", "/api/centres/P/inscrits?concours=DOUANES")
        self.assertEqual((code, liste["total"], liste["inscrits"][0]["npi"]), (200, 1, "1000000123"))
        code, rech = self.appeler("GET", "/api/inscrits/recherche?nom=DOS")
        self.assertEqual((code, [r["npi"] for r in rech]), (200, ["1000000123"]))


class ListeEtRechercheTests(TestCase):
    """Exigence de performance (INC-207) et non-régression de l'injection SQL."""

    @classmethod
    def setUpTestData(cls):
        creer_referentiel(capacite_p=10)
        cotonou, douanes = Centre.objects.get(code="C"), Concours.objects.get(code="DOUANES")
        Candidat.objects.bulk_create(
            [Candidat(npi=f"3{i:09d}", nom=f"NOM{i % 97}", prenoms="Test", date_naissance=date(1995, 1, 1))
             for i in range(5000)])
        Inscription.objects.bulk_create(
            [Inscription(concours=douanes, centre=cotonou, npi=f"3{i:09d}", date_epreuve=douanes.date_epreuve,
                         numero_table=f"C-{i + 1:04d}") for i in range(5000)])

    def test_liste_de_5000_inscrits_en_moins_de_2_s(self):
        debut = time.monotonic()
        r = APIClient().get("/api/centres/C/inscrits?concours=DOUANES")
        duree = time.monotonic() - debut
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["total"], 5000)
        self.assertEqual(r.data["inscrits"][0]["numero_table"], "C-0001")
        self.assertLess(duree, 2.0)

    def test_recherche_limitee_a_50(self):
        r = APIClient().get("/api/inscrits/recherche?nom=NOM")
        self.assertEqual(len(r.data), 50)

    def test_injection_sql_du_20_novembre_sans_effet(self):
        # « ' » seul : refusé proprement (moins de 2 caractères), pas d'erreur SQL
        self.assertEqual(APIClient().get("/api/inscrits/recherche", {"nom": "'"}).status_code, 400)
        for charge in ["''", "' OR '1'='1",
                       "' UNION SELECT npi, nom, date_naissance FROM candidats --"]:
            r = APIClient().get("/api/inscrits/recherche", {"nom": charge})
            self.assertEqual(r.status_code, 200, charge)
            self.assertEqual(r.data, [], charge)  # traité comme un nom, rien ne fuit
