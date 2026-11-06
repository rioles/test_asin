# Guide des tests — Inscriptions aux concours

Ce guide explique comment lancer les tests automatisés et ce que chacun vérifie.
Pour installer le projet (clone, venv, dépendances, `.env`, base), suivre d'abord **`guide_demarage_projet.md`**, étapes 1 à 6.

Commandes données pour **Git Bash / UCRT64**, à lancer depuis le dossier `test1` (celui de `manage.py`), **venv activé**.

---

## 1. Ce qu'il faut savoir avant de lancer les tests

D'habitude, Django crée une base séparée `test_…` pour les tests, puis la supprime.
Cela demande le droit PostgreSQL **`CREATEDB`**, que l'utilisateur `test_asin` n'a pas.

Le projet contourne cela avec un lanceur de tests (`test1/test_runner.py`) :
la variable **`DJANGO_TEST_SCHEMA`** lui dit d'utiliser un **schéma jetable** dans votre base existante.

- Le schéma est créé, les tests tournent dedans, puis il est **supprimé**.
- Vos tables et vos données (schéma `public`) **ne sont jamais touchées**.
- Aucune base n'est créée ni supprimée.

> **Toujours lancer les tests avec `DJANGO_TEST_SCHEMA=test_django` devant.**
> Sans elle, Django essaie de créer une base et échoue avec « droit refusé pour créer une base de données ».

Les tests démarrent eux-mêmes ce dont ils ont besoin (serveur Django, faux service d'identification) :
**inutile de lancer `runserver` ou `faux_service_identite.py`** pour les tests.

---

## 2. Lancer les tests

### Tous les tests de l'application (39 tests, environ 40 s)
assurez vous d'activer l'environnement 
```bash
DJANGO_TEST_SCHEMA=test_django python manage.py test test1.tests -v 2
```

### Seulement les tests d'intégration (10 tests, environ 20 s)
```bash
DJANGO_TEST_SCHEMA=test_django python manage.py test test1.tests.test_integration -v 2
```

### Seulement les tests unitaires et de concurrence (29 tests)
```bash
DJANGO_TEST_SCHEMA=test_django python manage.py test test1.tests.test_inscriptions -v 2
```

### Un seul test
```bash
DJANGO_TEST_SCHEMA=test_django python manage.py test test1.tests.test_integration.InscriptionHttpTests.test_30_requetes_http_simultanees_pour_10_places -v 2
```

### Tests du script SQL de réparation de l'export (15 tests)
Ce test-là crée lui-même un schéma jetable : pas besoin de la variable.
```bash
python -X utf8 -m unittest reparation.test_reparation -v
```

### Variante PowerShell
```powershell
$env:DJANGO_TEST_SCHEMA = "test_django"
python manage.py test test1.tests -v 2
```

### Résultat attendu
```
Ran 39 tests in …s

OK
```

> Des lignes comme `appel identite GET /identite/9000000001 -> timeout/erreur (5012 ms)` sont **normales** :
> c'est le journal qui montre que l'application a bien coupé le service lent au bout de 5 s.

---

## 3. Ce que vérifient les tests

### `test1/tests/test_inscriptions.py` : tests unitaires et de concurrence (29)

| Classe | Ce qu'elle vérifie | Incident |
|---|---|---|
| `RegleAgeTests` | âge au 31/12 : né le 20/06/1991 → 35 ans accepté ; 31/12/1990 → 36 ans refusé | INC-205 |
| `RegleClotureTests` | Trésor ouvert à 23 h heure du Bénin, fermé après 23 h 59 ; indépendant du fuseau du serveur | INC-204 |
| `InscriptionTests` | format `P-0001`, numéro unique dans le centre, double clic, même jour, capacité, NPI inconnu, statut « en attente » | INC-201 à 203, 208 |
| `ApiTests` | 201 puis 200 au second clic, 400 sur saisie invalide, convocation sans appel au service, liste en 3 requêtes | INC-203, 206, 207 |
| `IdentiteClientTests` | vrai serveur HTTP lent : coupure à 5 s, même quand il répond octet par octet ; 404 ; service arrêté | INC-206 |
| `ConcurrenceTests` | **requêtes simultanées** : 40 candidats pour 20 places ; 10 clics du même candidat ; deux concours du même jour | INC-201, 202, 203 |

### `test1/tests/test_integration.py` : tests d'intégration (10)

Ici **rien n'est simulé dans l'application** :
1. un **vrai serveur Django** démarre (`LiveServerTestCase`), branché sur **PostgreSQL** ;
2. un **faux service d'identification** démarre, qui est lui-même un vrai serveur HTTP
   (NPI normal → réponse en 50 ms ; NPI en `9…` → réponse en 8 s ; `0000000000` → 404) ;
3. le test envoie de **vraies requêtes HTTP**, comme un navigateur ou curl, souvent **en même temps** ;
4. il vérifie les réponses **et** le contenu de la base.

| Test | Scénario | Résultat vérifié |
|---|---|---|
| `test_30_requetes_http_simultanees_pour_10_places` | 30 candidats cliquent au même instant | 10 × 201 (P-0001 à P-0010), 20 × 409 « centre complet » |
| `test_double_clic_http_simultane_une_seule_inscription` | même candidat, 8 envois simultanés | 1 inscription, 8 réponses avec le même id |
| `test_deux_concours_du_meme_jour_en_meme_temps` | Douanes et Impôts envoyés ensemble | 1 seule inscription |
| `test_service_lent_inscription_en_attente_en_moins_de_6_s` | service à 8 s | réponse en moins de 6 s, `EN_ATTENTE_VERIFICATION` |
| `test_service_lent_ne_bloque_ni_les_autres_ni_les_convocations` | 5 inscriptions bloquées sur le service lent | **pendant ce temps**, convocation en moins de 1 s et une autre inscription passe |
| `test_npi_inconnu_refuse` | NPI `0000000000` | 422, aucune place consommée |
| `test_parcours_complet_inscription_convocation_liste` | inscription → convocation → liste → recherche | tout est cohérent |
| `test_liste_de_5000_inscrits_en_moins_de_2_s` | 5 000 inscrits à Cotonou | liste en moins de 2 s |
| `test_recherche_limitee_a_50` | recherche large | 50 résultats au plus |
| `test_injection_sql_du_20_novembre_sans_effet` | charges de l'attaque du 20/11 | rien ne fuit |

### `reparation/test_reparation.py` : script SQL de réparation (15)

Charge `base_inscriptions.sql` dans un schéma jetable, applique `reparer_export.sql`, puis vérifie :
- plus aucun numéro ni aucune inscription en double ;
- Lokossa : aucune suppression, et la liste des 7 inscrits au-delà de la capacité ;
- le script **rejoué 2 fois** ne change rien ;
- la base refuse désormais un doublon, et 10 connexions simultanées sur 3 places → exactement 3 acceptées.

---

## 4. En cas de problème

| Message | Cause | Solution |
|---|---|---|
| `bash: manage.py: command not found` | `python` oublié | `DJANGO_TEST_SCHEMA=test_django python manage.py test …` |
| `droit refusé pour créer une base de données` | variable `DJANGO_TEST_SCHEMA` absente | la mettre devant la commande |
| `DJANGO_TEST_SCHEMA doit commencer par « test_ »` | nom de schéma refusé (sécurité) | utiliser `test_django` |
| `No module named 'django'` | venv non activé | `source venv/Scripts/activate` |
| `password authentication failed` | `.env` incorrect | vérifier `DB_USER` / `DB_PASSWORD` |
| `UnicodeEncodeError` (tests de réparation) | console Windows en cp1252 | garder `-X utf8` dans la commande |
| `ConnectionAbortedError` dans la sortie | client parti au bout de 5 s pendant que le faux service répondait | sans gravité si le test finit par `ok` |
