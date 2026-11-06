# Simulation manuelle avec curl

Tester l'API à la main en 5 minutes.
Commandes pour **Git Bash**, depuis le dossier `test1`, **venv activé**.

---

## 1. Démarrer (2 terminaux)

**Terminal 1** : le faux service d'identification
```bash
python outils/faux_service_identite.py
```

**Terminal 2** : l'API
```bash
python manage.py donnees_demo     # seulement si la base est vide (crée concours et centres)
python manage.py runserver
```

Les curls se tapent dans un **3ᵉ terminal**.

---

## 2. Exemple simple : remplir le centre de Lokossa (3 places)

### Inscrire 3 candidats
```bash
curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"2000000001","date_naissance":"1995-03-01","concours":"DOUANES","centre":"L"}'

curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"2000000002","date_naissance":"1995-03-01","concours":"TRESOR","centre":"L"}'

curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"2000000003","date_naissance":"1995-03-01","concours":"IMPOTS","centre":"L"}'
```
✅ **Attendu** : numéros de table **L-0001**, **L-0002**, **L-0003**.
Le numéro suit dans le centre, même si les concours sont différents.

### Inscrire un 4ᵉ candidat
```bash
curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"2000000004","date_naissance":"1995-03-01","concours":"DOUANES","centre":"L"}'
```
✅ **Attendu** : refusé, `"code":"CENTRE_COMPLET"` (le centre est plein).

### Voir la liste des inscrits
```bash
curl -s "http://127.0.0.1:8000/api/centres/L/inscrits?concours=DOUANES"
```
✅ **Attendu** : le candidat `2000000001` avec le numéro `L-0001`.

> Ne pas oublier `?concours=...` et les **guillemets** autour de l'adresse.

### Dans le terminal 2, vous voyez
```
"POST /api/inscriptions HTTP/1.1" 201 177     ← 201 = inscription créée (177 = taille, pas une erreur)
"POST /api/inscriptions HTTP/1.1" 409 ...     ← 409 = refusée (centre complet)
```

### Recommencer depuis zéro
Lokossa est maintenant plein. Pour vider Lokossa (⚠️ supprime ses inscriptions, base de test uniquement) :
```bash
python manage.py shell -c "from test1.models import Centre, Inscription; Inscription.objects.filter(centre__code='L').delete(); Centre.objects.filter(code='L').update(inscrits=0, dernier_numero=0)"
```

---

## 3. Options avancées

> Un NPI déjà inscrit renvoie `200` (on lui redonne son inscription) au lieu de `201`.
> Pour refaire un essai, **changez les derniers chiffres du NPI**.

### Double clic : le même candidat envoie 5 fois en même temps
```bash
for i in 1 2 3 4 5; do
  curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
    -d '{"npi":"4000000001","date_naissance":"1995-03-01","concours":"DOUANES","centre":"P"}' &
done; wait
```
✅ Une seule inscription : **même `id` et même numéro** dans les 5 réponses.

### 10 candidats en même temps
```bash
for i in 0 1 2 3 4 5 6 7 8 9; do
  curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
    -d "{\"npi\":\"300000000$i\",\"date_naissance\":\"1995-03-01\",\"concours\":\"DOUANES\",\"centre\":\"A\"}" &
done; wait
curl -s "http://127.0.0.1:8000/api/centres/A/inscrits?concours=DOUANES"
```
✅ 10 numéros **tous différents** (A-0001 à A-0010).

### Deux concours le même jour (Douanes et Impôts : 12/12)
```bash
curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"4000000001","date_naissance":"1995-03-01","concours":"IMPOTS","centre":"P"}'
```
✅ Refusé : `"code":"MEME_JOUR"`.

### Âge : 35 ans au 31 décembre au plus
```bash
curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"5000000001","date_naissance":"1991-06-20","concours":"DOUANES","centre":"C"}'

curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"5000000002","date_naissance":"1990-12-31","concours":"DOUANES","centre":"C"}'
```
✅ Le 1ᵉʳ (35 ans) est **accepté**, le 2ᵉ (36 ans) est refusé : `"code":"AGE"`.

### NPI inconnu
```bash
curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"0000000000","date_naissance":"1995-03-01","concours":"DOUANES","centre":"C"}'
```
✅ Refusé : `"code":"NPI_INCONNU"`.

### Service d'identification lent (NPI qui commence par 9 : le faux service met 20 s)
```bash
time curl -s -X POST http://127.0.0.1:8000/api/inscriptions -H "Content-Type: application/json" \
  -d '{"npi":"9000000001","date_naissance":"1995-03-01","concours":"DOUANES","centre":"N"}'
```
✅ Réponse en **environ 5 s** (pas 20 s), avec `"statut":"EN_ATTENTE_VERIFICATION"`.

### Convocation
Remplacer `1` par un `id` reçu dans une réponse :
```bash
curl -s http://127.0.0.1:8000/api/inscriptions/1/convocation
```
✅ Numéro de table, nom, prénoms, concours, centre. Réponse immédiate.

### Recherche par nom (2 lettres au moins)
```bash
curl -s "http://127.0.0.1:8000/api/inscrits/recherche?nom=dos"
```
✅ Les inscrits dont le nom commence par « dos » (50 au plus).

### Tentative d'injection SQL
```bash
curl -s -G http://127.0.0.1:8000/api/inscrits/recherche --data-urlencode "nom=' OR '1'='1"
```
✅ `[]` : rien ne fuit.

---

## Les codes de réponse

| Code | Sens |
|---|---|
| 201 | inscription créée |
| 200 | déjà inscrit : on redonne la même inscription |
| 400 | saisie invalide, ou `?concours=` oublié |
| 409 | `CENTRE_COMPLET`, `DEJA_INSCRIT`, `MEME_JOUR` |
| 422 | `AGE`, `NPI_INCONNU` |
| `Failed to connect` | `runserver` n'est pas lancé |
