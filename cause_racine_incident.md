# Analyse des incidents — causes racines et liens

> Croisement du **dossier technique** (architecture, déroulement d'une inscription,
> schéma base, format du journal) et du **journal de production**.
> Horodatages du journal en **UTC** ; heure du Bénin = **UTC+1**.



## Synthèse en une page

| Incident | Cause racine | Défaut | Liens |
|----------|-------------|--------|-------|
| **INC-201** | Étape 6 `MAX+1` non atomique + étape 7 (HTTP) en transaction → fenêtre 20–60 s | **A + B** | Même défaut que INC-202 (numéros) et INC-203 (doublon) ; aggravé par INC-206 |
| **INC-202** | Étape 5 (`COUNT < capacite`) **et** étape 6 non atomiques, sans contrainte | **A** | Même défaut que INC-201 ; la lenteur d'INC-206 aggrave |
| **INC-203** | Étape 4 `SELECT` puis `INSERT` sans `UNIQUE (npi, concours)` ; correctif applicatif tardif (20/11) | **A** | Même défaut que INC-201/202 ; double-clic aggravé par la lenteur d'INC-206 |
| **INC-204** | Étape 2 : `cloture` UTC comparée à heure serveur Bénin **sans conversion** | **C** | Isolé |
| **INC-205** | Étape 3 : `jours/365 > 35` — formule fausse (faux positifs 1991 **et 1992**) | **D** | Isolé |
| **INC-206** | Étape 7 : HTTP « configuration par défaut » (pas de timeout, pas de circuit breaker) **dans la transaction** | **B** | Aggrave INC-201/202/203 (fenêtre de course ×1000) |
| **INC-207** | Liste des inscrits : **N+1** décrit au dossier + **aucun index** + **pas de pagination** | **D + E** | Isolé, mais même racine « dossier décrit une règle non scalable » que INC-205/208 |
| **INC-208** | Étape 4 : « interdiction même jour » — règle métier trop restrictive | **D** | Isolé (défaut de spécification, pas d'exécution) |

**Lecture d'ensemble** : sur 8 incidents, **3 (INC-201, 202, 203) partagent la même cause racine** (défaut A), **1 (INC-206) aggrave ces 3 mêmes incidents** (défaut B), et **1 (INC-204)** est isolé sur les fuseaux. Restent **3 incidents (INC-205, 207, 208)** qui sont trois manifestations distinctes du même **défaut de gouvernance** (défaut D) : *le dossier technique décrit comme correctes des règles fausses ou non scalables*. La **contrainte transverse E** (aucune contrainte en base) est ce qui rend le défaut A **impossible à corriger durablement** par du code applicatif seul.

---

## INC-201 — Même numéro de table `P-0464` pour deux candidats

### Règle du dossier technique (étape 6)

> « Calcul du numéro de table : **plus grand numéro du centre + 1**. »

Cette règle est un **`SELECT MAX(...) + 1`** — une lecture suivie d'une écriture,
**sans verrou, sans séquence, sans contrainte d'unicité** (le dossier précise :
*« Index : clés primaires uniquement. Aucune contrainte d'unicité. »*).

### Preuve dans le journal

Deux requêtes **simultanées** sur le centre P, toutes deux lentes (~20–35 s),
obtiennent le **même numéro** :

```text
08:21:39.070  WARN  req:a061413f  identite 3076016910  (22766 ms)
08:21:39.081  INFO  req:a061413f  POST /api/inscriptions -> 201  npi=3076016910  numero=P-0464
08:21:47.414  WARN  req:a93cfec6  identite 7984581920  (33410 ms)
08:21:47.432  INFO  req:a93cfec6  POST /api/inscriptions -> 201  npi=7984581920  numero=P-0464