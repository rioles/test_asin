# Guide de démarrage du projet — Inscriptions aux concours

Ce guide part de zéro : cloner le projet, l'installer, préparer la base, lancer l'API et l'essayer avec curl.
Pour les tests automatisés, voir **`guid_demarage_test.md`**.

Les commandes sont données pour **Git Bash / UCRT64** (le terminal utilisé sur ce projet).
Quand PowerShell est différent, la variante est indiquée.

---

## 0. Prérequis

| Outil | Version | Vérifier |
|---|---|---|
| Python | **3.12 ou plus** (Django 6.1 l'exige) | `python --version` |
| PostgreSQL | 14 ou plus (testé avec 18) | `psql --version` |
| Git | toute version récente | `git --version` |

---

## 1. Cloner le projet

```bash
git clone <URL_DU_DEPOT> test_asin
cd test_asin/test1
```

Toutes les commandes suivantes se lancent **depuis ce dossier `test1`** (celui qui contient `manage.py`).

---

## 2. Créer et activer l'environnement virtuel (venv)

Le venv isole les bibliothèques du projet de celles du reste de l'ordinateur.

```bash
python -m venv venv
source venv/Scripts/activate        # Git Bash / UCRT64 sous Windows
```

| Terminal | Commande d'activation |
|---|---|
| Git Bash / UCRT64 (Windows) | `source venv/Scripts/activate` |
| PowerShell (Windows) | `venv\Scripts\Activate.ps1` |
| Linux / macOS | `source venv/bin/activate` |

Une fois activé, **`(venv)`** apparaît dans le terminal. À refaire à chaque nouveau terminal.

> PowerShell refuse d'exécuter le script ? Lancer une fois :
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## 3. Installer les dépendances

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Bibliothèques principales : Django 6.1, Django REST Framework, psycopg 3 (pilote PostgreSQL),
python-dotenv (lecture du `.env`), tzdata (fuseau horaire du Bénin sous Windows).

---

## 4. Préparer PostgreSQL

Se connecter en administrateur (`psql -U postgres`, ou pgAdmin) et créer l'utilisateur et la base :

```sql
CREATE USER test_asin WITH PASSWORD 'votre_mot_de_passe';
CREATE DATABASE inscription_tma_db OWNER test_asin;
```

> Pour les tests, `test_asin` n'a **pas** besoin du droit `CREATEDB` : voir `guid_demarage_test.md`.

---

## 5. Configurer le fichier `.env`

```bash
cp .env.example .env
```

Puis ouvrir `.env` et remplir au moins `DB_PASSWORD` (et `DB_NAME`, `DB_USER` s'ils diffèrent).
Le fichier `.env` contient un mot de passe : **il ne doit jamais être envoyé dans Git** (ajouter `.env` au `.gitignore`).

---

## 6. Créer les tables

```bash
python manage.py migrate
python manage.py check          # doit afficher : System check identified no issues
```

---

## 7. Charger les données de démonstration

```bash
python manage.py donnees_demo
```

Crée 3 concours (DOUANES, IMPOTS, TRESOR) et 5 centres (C, P, L, N, A).
**Lokossa (L) n'a que 3 places**, pour voir facilement le refus « centre complet ».
La commande peut être relancée sans risque.

---

## 8. Démarrer le projet (2 terminaux)

L'application interroge le **service national d'identification**. Il n'est pas accessible en local,
on démarre donc un **faux service** qui l'imite.

**Terminal 1 : faux service d'identification** (port 8081)
```bash
source venv/Scripts/activate
python outils/faux_service_identite.py
```

**Terminal 2 : l'API Django** (port 8000)
```bash
source venv/Scripts/activate
python manage.py runserver 127.0.0.1:8000
```

> Utiliser **`127.0.0.1`** et non `localhost` : sous Windows, `localhost` fait perdre environ 2 secondes par requête.

Le faux service répond selon le NPI envoyé :

| NPI envoyé | Réponse du faux service | Ce que ça permet de vérifier |
|---|---|---|
| NPI normal (ex. `1234567890`) | nom et prénoms, tout de suite | inscription normale, statut `VALIDEE` |
| `0000000000` | « NPI inconnu » (404) | refus `NPI_INCONNU` |
| commence par **9** (ex. `9876543210`) | répond au bout de **20 s** | l'application coupe à **5 s** et enregistre `EN_ATTENTE_VERIFICATION` |

---

## 9. Essayer l'API avec curl (Terminal 3)

```bash
B=http://127.0.0.1:8000/api
```

| # | Ce qu'on teste | Commande | Résultat attendu |
|---|---|---|---|
| 1 | Inscription normale | `curl -X POST $B/inscriptions -H "Content-Type: application/json" -d '{"npi":"1234567890","date_naissance":"1995-03-01","concours":"DOUANES","centre":"P"}'` | **201**, `P-0001`, `VALIDEE` |
| 2 | Double clic (INC-203) | même commande que 1 | **200**, même `id`, même numéro |
| 3 | Même jour (INC-208, règle) | `curl -X POST $B/inscriptions -H "Content-Type: application/json" -d '{"npi":"1234567890","date_naissance":"1995-03-01","concours":"IMPOTS","centre":"P"}'` | **409** `MEME_JOUR` |
| 4 | Âge : né le 20/06/1991 (INC-205) | `curl -X POST $B/inscriptions -H "Content-Type: application/json" -d '{"npi":"1234567891","date_naissance":"1991-06-20","concours":"DOUANES","centre":"P"}'` | **201** accepté |
| 5 | 36 ans | `curl -X POST $B/inscriptions -H "Content-Type: application/json" -d '{"npi":"1234567892","date_naissance":"1990-12-31","concours":"DOUANES","centre":"P"}'` | **422** `AGE` |
| 6 | NPI inconnu | `curl -X POST $B/inscriptions -H "Content-Type: application/json" -d '{"npi":"0000000000","date_naissance":"1995-03-01","concours":"DOUANES","centre":"P"}'` | **422** `NPI_INCONNU` |
| 7 | Saisie invalide | `curl -X POST $B/inscriptions -H "Content-Type: application/json" -d '{"npi":"12AB","date_naissance":"1995-03-01","concours":"XXX","centre":"P"}'` | **400** |
| 8 | Service lent (INC-206) | `curl -w "\nDurée : %{time_total} s\n" -X POST $B/inscriptions -H "Content-Type: application/json" -d '{"npi":"9876543210","date_naissance":"1995-03-01","concours":"DOUANES","centre":"C"}'` | **201** `EN_ATTENTE_VERIFICATION` en **environ 5 s** |
| 10 | Convocation (remplacer `1` par l'id reçu au curl 1) | `curl $B/inscriptions/1/convocation` | nom, prénoms, numéro, centre |
| 11 | Liste des inscrits (INC-207) | `curl "$B/centres/L/inscrits?concours=TRESOR"` | liste triée par numéro |
| 12 | Recherche par nom | `curl "$B/inscrits/recherche?nom=DOS"` | 50 résultats au plus |
| 13 | Injection SQL du 20/11 | `curl "$B/inscrits/recherche?nom=%27%20UNION%20SELECT%20npi%2C%20nom%2C%20date_naissance%20FROM%20candidats%20--"` | `[]` : rien ne fuit |

**9. Requêtes simultanées (INC-201 / INC-202)** : 5 candidats **en même temps** pour les 3 places de Lokossa :
```bash
for i in 1 2 3 4 5; do curl -s -X POST $B/inscriptions -H "Content-Type: application/json" -d "{\"npi\":\"555555555$i\",\"date_naissance\":\"1995-03-01\",\"concours\":\"TRESOR\",\"centre\":\"L\"}" & done; wait; echo
```
Résultat attendu : **3 acceptés** (L-0001, L-0002, L-0003) et **2 refusés** `CENTRE_COMPLET`, sans aucun numéro en double.

> **PowerShell** : `curl` y est un alias d'une autre commande, utiliser **`curl.exe`**.
> Les guillemets du JSON passent mal en PowerShell : le plus simple est de lancer ces curls dans Git Bash.
> Variante PowerShell sans curl :
> ```powershell
> Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/inscriptions -ContentType "application/json" -Body '{"npi":"1234567890","date_naissance":"1995-03-01","concours":"DOUANES","centre":"P"}'
> ```

---

## 10. Remettre la base à zéro (pour recommencer les essais)

Un NPI ne peut s'inscrire qu'une fois. Pour rejouer les curls depuis le début :

```bash
python manage.py shell -c "from test1.models import *; Inscription.objects.all().delete(); Candidat.objects.all().delete(); Centre.objects.update(inscrits=0, dernier_numero=0)"
```

> **Attention** : efface **toutes** les inscriptions et tous les candidats. À utiliser uniquement sur la base de développement.

---

## 11. Les URL de l'API

| Méthode | URL | Rôle |
|---|---|---|
| POST | `/api/inscriptions` | inscrire un candidat (`npi`, `date_naissance`, `concours`, `centre`) |
| GET | `/api/inscriptions/{id}/convocation` | convocation (lue en base, sans appeler le service d'identification) |
| GET | `/api/centres/{code}/inscrits?concours=CODE` | liste des inscrits d'un centre pour un concours |
| GET | `/api/inscrits/recherche?nom=…` | recherche par début de nom, 50 résultats au plus |

Codes de réponse de `POST /api/inscriptions` :

| Code | Signification |
|---|---|
| 201 | inscription créée (`VALIDEE` ou `EN_ATTENTE_VERIFICATION`) |
| 200 | inscription déjà existante, renvoyée telle quelle (double clic) |
| 400 | saisie invalide (NPI, date, concours ou centre) |
| 403 | `CLOTURE` : inscriptions closes |
| 409 | `CENTRE_COMPLET`, `DEJA_INSCRIT` ou `MEME_JOUR` |
| 422 | `AGE` ou `NPI_INCONNU` |

---

## 12. Où se trouve quoi

| Dossier / fichier | Contenu |
|---|---|
| `test1/models/` | modèles : `Concours`, `Centre`, `Candidat`, `Inscription` |
| `test1/services/inscription_service.py` | règles d'inscription : clôture, âge, doublons, capacité, numéro |
| `test1/services/identite_client.py` | appel au service d'identification, limité à 5 s |
| `test1/views/inscription_view.py` | les 4 endpoints |
| `test1/serializers.py` | contrôle de forme (étape 1) |
| `test1/urls.py` | routes `/api/…` |
| `test1/tests/` | tests automatisés (voir `guid_demarage_test.md`) |
| `outils/faux_service_identite.py` | faux service d'identification pour le développement |
| `reparation/` | script SQL de réparation de l'export et ses tests |
| `rapports/` | rapport d'incident INC-206 et incident non signalé (injection SQL) |

---

## Problèmes fréquents

| Message | Cause | Solution |
|---|---|---|
| `bash: manage.py: command not found` | `python` oublié devant | `python manage.py …` |
| `No module named 'django'` | venv non activé | `source venv/Scripts/activate` |
| `password authentication failed` | mauvais mot de passe dans `.env` | corriger `DB_PASSWORD` |
| `relation "inscriptions" does not exist` | tables non créées | `python manage.py migrate` |
| `{"detail":"No Centre matches…"}` (404) | pas de données | `python manage.py donnees_demo` |
| Inscriptions toujours `EN_ATTENTE_VERIFICATION` | faux service non démarré | Terminal 1 : `python outils/faux_service_identite.py` |
| Chaque requête prend environ 2 s de plus | `localhost` sous Windows | utiliser `127.0.0.1` |
