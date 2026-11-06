"""
Test du script reparer_export.sql sur un vrai PostgreSQL.

    ..\\venv\\Scripts\\python.exe -m unittest reparation.test_reparation -v

Le test :
  * crée un schéma jetable (jamais « public » : l'export commence par des DROP TABLE
    dont les noms sont ceux des tables Django) ;
  * y charge base_inscriptions.sql, applique la réparation, vérifie le résultat ;
  * rejoue la réparation et vérifie que rien ne change ;
  * tente de reproduire chaque incident (y compris par requêtes simultanées) ;
  * supprime le schéma.
Connexion : variables DB_* du fichier .env (comme Django).
"""
import os
import threading
import unittest
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
EXPORT = RACINE / "base_inscriptions.sql"
REPARATION = Path(__file__).resolve().parent / "reparer_export.sql"
load_dotenv(RACINE / ".env")


def connecter(schema=None):
    conn = psycopg.connect(
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"), autocommit=True,
    )
    if schema:
        conn.execute(f'SET search_path TO "{schema}"')  # uniquement le schéma jetable
    return conn


def empreinte(conn):
    """Empreinte de tout le contenu métier + tables de réparation."""
    tables = ["concours", "centres", "candidats", "inscriptions", "reparation_arrivees",
              "reparation_doublons_supprimes", "reparation_numeros", "decision_capacite"]
    res = {}
    for t in tables:
        cols = "*" if t != "reparation_doublons_supprimes" else \
            "id, concours_id, centre_id, npi, numero_table, statut, cree_le, conservee_id"
        if t == "reparation_numeros":
            cols = "inscription_id, centre_id, npi, ancien_numero, nouveau_numero"
        res[t] = conn.execute(
            f"SELECT md5(string_agg(x::text, '|' ORDER BY x::text)) FROM (SELECT {cols} FROM {t}) x"
        ).fetchone()[0]
    return res


class ReparationExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = f"essai_reparation_{uuid.uuid4().hex[:8]}"
        with connecter() as c:
            cls.tables_public = c.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0]
            c.execute(f'CREATE SCHEMA "{cls.schema}"')
        cls.conn = connecter(cls.schema)
        cls.conn.execute(EXPORT.read_text(encoding="utf-8"))
        cls.avant = {
            "inscriptions": cls.q1("SELECT count(*) FROM inscriptions"),
            "lokossa": cls.q1("SELECT count(*) FROM inscriptions i JOIN centres c ON c.id = i.centre_id WHERE c.code = 'L'"),
        }
        cls.conn.execute(REPARATION.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        with connecter() as c:
            c.execute(f'DROP SCHEMA "{cls.schema}" CASCADE')
            apres = c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0]
        assert apres == cls.tables_public, "le schéma public a été modifié !"

    @classmethod
    def q1(cls, sql, *params):
        return cls.conn.execute(sql, params).fetchone()[0]

    def q(self, sql, *params):
        return self.conn.execute(sql, params).fetchall()

    def numero(self, id_):
        return self.q1("SELECT numero_table FROM inscriptions WHERE id = %s", id_)

    # ------------------------------------------------------------------ données
    def test_plus_aucun_doublon(self):
        self.assertEqual(self.q("SELECT centre_id, numero_table FROM inscriptions GROUP BY 1, 2 HAVING count(*) > 1"), [])
        self.assertEqual(self.q("SELECT npi, concours_id FROM inscriptions GROUP BY 1, 2 HAVING count(*) > 1"), [])

    def test_inc203_doublons_supprimes_premiere_requete_conservee(self):
        supprimes = dict(self.q("SELECT id, conservee_id FROM reparation_doublons_supprimes"))
        # double clic : on garde la requête ARRIVÉE la première (journal), pas forcément la plus petite id
        self.assertEqual(supprimes, {4750: 4749, 5057: 5056, 5063: 5062, 5070: 5068,
                                     5072: 5071, 5074: 5075, 5080: 5079})
        self.assertEqual(self.q1("SELECT count(*) FROM inscriptions"), self.avant["inscriptions"] - 7)

    def test_inc201_p0464_garde_par_le_premier_arrive(self):
        self.assertEqual(self.numero(5066), "P-0464")   # arrivée 08:21:14.000
        self.assertEqual(self.numero(5065), "P-0614")   # arrivée 08:21:16.300 → P max + 1

    def test_cotonou_seuls_les_seconds_changent_de_numero(self):
        self.assertEqual(self.numero(5056), "C-3305")
        self.assertEqual(self.numero(5060), "C-3306")
        self.assertEqual(self.numero(5068), "C-3308")
        changes = dict(self.q("""SELECT inscription_id, nouveau_numero FROM reparation_numeros r
                                 JOIN centres c ON c.id = r.centre_id WHERE c.code = 'C'"""))
        self.assertEqual(changes, {5058: "C-4177", 5062: "C-4178", 5067: "C-4179",
                                   5076: "C-4180", 5081: "C-4181"})

    def test_lokossa_aucune_suppression_et_liste_des_7_au_dela(self):
        self.assertEqual(self.q1("SELECT count(*) FROM inscriptions i JOIN centres c ON c.id = i.centre_id WHERE c.code = 'L'"),
                         self.avant["lokossa"])
        self.assertEqual(self.q1("SELECT count(*) FROM reparation_doublons_supprimes d JOIN centres c ON c.id = d.centre_id WHERE c.code = 'L'"), 0)
        # numéros dans l'ordre d'arrivée : les 4 premiers occupent L-0297 … L-0300
        ordre = [5045, 5046, 5047, 5049, 5052, 5050, 5048, 5054, 5051, 5053, 5055]
        self.assertEqual([self.numero(i) for i in ordre], [f"L-{n:04d}" for n in range(297, 308)])
        liste = self.q("SELECT inscription_id, rang_arrivee, numero_table, decision FROM decision_capacite ORDER BY rang_arrivee")
        self.assertEqual(liste, [(i, 300 + k, f"L-{300 + k:04d}", None) for k, i in enumerate(ordre[4:], 1)])
        self.assertEqual(len(self.q("SELECT * FROM decision_capacite_a_valider")), 7)

    def test_personnes_a_prevenir(self):
        motifs = dict(self.q("SELECT motif, count(*) FROM reparation_a_prevenir GROUP BY motif"))
        self.assertEqual(motifs, {"NOUVEAU_NUMERO": 9,                  # 6 hors Lokossa + 3 à Lokossa
                                  "CONVOCATION_EN_DOUBLE_ANNULEE": 7,
                                  "CAPACITE_DEPASSEE_DECISION_EN_ATTENTE": 7})

    def test_compteur_des_centres(self):
        self.assertEqual(self.q("""SELECT c.code FROM centres c WHERE c.inscrits <>
                                   (SELECT count(*) FROM inscriptions i WHERE i.centre_id = c.id)"""), [])
        self.assertEqual(self.q1("SELECT inscrits FROM centres WHERE code = 'L'"), 307)

    # ------------------------------------------------------------- rejouable
    def test_rejouer_le_script_ne_change_rien(self):
        avant = empreinte(self.conn)
        self.conn.execute(REPARATION.read_text(encoding="utf-8"))
        self.conn.execute(REPARATION.read_text(encoding="utf-8"))
        self.assertEqual(empreinte(self.conn), avant)

    def test_refuse_de_tourner_sur_le_schema_django(self):
        self.conn.execute("CREATE TABLE django_migrations (id int)")
        try:
            with self.assertRaisesRegex(psycopg.errors.RaiseException, "Django"):
                self.conn.execute(REPARATION.read_text(encoding="utf-8"))
            self.conn.execute("ROLLBACK")  # le script a ouvert une transaction
        finally:
            self.conn.execute("DROP TABLE django_migrations")

    # ------------------------------------------- les incidents ne passent plus
    def _inserer(self, conn, id_, centre_code, concours_code, npi, numero):
        conn.execute(
            """INSERT INTO inscriptions (id, concours_id, centre_id, npi, numero_table, statut, cree_le)
               SELECT %s, co.id, ce.id, %s, %s, 'validee', now() AT TIME ZONE 'UTC'
               FROM concours co, centres ce WHERE co.code = %s AND ce.code = %s""",
            (id_, npi, numero, concours_code, centre_code))

    def _id_libre(self):
        return self.q1("SELECT max(id) + 1 FROM inscriptions") + 1000

    def test_numero_en_double_refuse(self):
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._inserer(self.conn, self._id_libre(), "P", "TRESOR", "9999999901", "P-0464")

    def test_inscription_en_double_refusee(self):
        npi, numero = self.q("SELECT npi, numero_table FROM inscriptions WHERE id = 5066")[0]
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._inserer(self.conn, self._id_libre(), "P", "DOUANES", npi, "P-9001")

    def test_deux_concours_le_meme_jour_refuse(self):
        npi = self.q1("SELECT npi FROM inscriptions WHERE id = 5066")  # inscrit DOUANES (12/12)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._inserer(self.conn, self._id_libre(), "P", "IMPOTS", npi, "P-9002")

    def test_lokossa_complet_refuse_tout_nouvel_inscrit(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._inserer(self.conn, self._id_libre(), "L", "TRESOR", "9999999903", "L-0400")

    def test_inscriptions_simultanees_ne_depassent_pas_la_capacite(self):
        """10 connexions inscrivent en même temps sur les 3 dernières places d'Abomey."""
        self.conn.execute("UPDATE centres SET capacite = inscrits + 3 WHERE code = 'A'")
        base = self._id_libre()
        depart = threading.Barrier(10)
        resultats = []

        def inscrire(k):
            with connecter(self.schema) as c:
                depart.wait()
                try:
                    self._inserer(c, base + k, "A", "TRESOR", f"88888888{k:02d}", f"A-{9000 + k}")
                    resultats.append("ok")
                except psycopg.errors.CheckViolation:
                    resultats.append("complet")

        threads = [threading.Thread(target=inscrire, args=(k,)) for k in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        try:
            self.assertEqual(sorted(resultats), ["complet"] * 7 + ["ok"] * 3)
            self.assertEqual(self.q1("SELECT capacite - inscrits FROM centres WHERE code = 'A'"), 0)
        finally:
            self.conn.execute("DELETE FROM inscriptions WHERE id >= %s", (base,))
            self.conn.execute("UPDATE centres SET capacite = 600 WHERE code = 'A'")

    def test_suppression_libere_la_place(self):
        id_ = self._id_libre()
        self._inserer(self.conn, id_, "A", "TRESOR", "9999999904", "A-9100")
        n = self.q1("SELECT inscrits FROM centres WHERE code = 'A'")
        self.conn.execute("DELETE FROM inscriptions WHERE id = %s", (id_,))
        self.assertEqual(self.q1("SELECT inscrits FROM centres WHERE code = 'A'"), n - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
