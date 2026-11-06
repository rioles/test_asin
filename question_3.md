# Causes racines des incidents et liens entre eux

> **Question** : trouvez la cause racine de chaque incident en croisant le dossier technique et le journal. Montrez les liens entre incidents.

**Sources croisées**

| Source | Contenu |
|---|---|
| **Dossier technique** | déroulement de l'inscription en 8 étapes, architecture, schéma de la base |
| **Journal** `journal_production.log` | 18/11 00:00 → 21/11 07:00 UTC : 8 221 requêtes, 4 556 appels au service d'identification (60 WARN, 1 ERROR) |
| **Export** `base_inscriptions.sql` | 21/11, 08 h 00 (heure du Bénin) : 6 400 inscriptions, 19 303 candidats |

Rappels utiles pour lire le journal :
- les horodatages sont en **UTC** (heure du Bénin = UTC + 1) ;
- une ligne de requête est écrite **à la fin** de son traitement, avec sa durée. L'**heure d'arrivée** d'une requête vaut donc horodatage − durée ;
- `cree_le` dans la base correspond lui aussi à la **fin** de la requête.

---

## A. Schéma de la base (audit)

| Contrôle | Résultat |
| :--- | :--- |
| **Contraintes PRIMARY KEY** | 4 (une par table) |
| **Contraintes NOT NULL** | 20 |
| **Contraintes FOREIGN KEY** | 2 (`inscriptions.centre_id`, `inscriptions.concours_id`) |
| **Contraintes UNIQUE** | 0 ⚠️ |
| **Contraintes CHECK** | 0 ⚠️ |
| **Index secondaires** | 0 ⚠️ |
| **Type de `cloture`** | `timestamp without time zone` ⚠️ |

L'audit confirme le dossier (*« Index : clés primaires uniquement. Aucune contrainte d'unicité. »*) : **la base ne protège aucune règle métier**. Tout repose sur le code, qui fait des contrôles en « lire puis écrire » sans verrou.

---

## B. INC-201 — Numéros de table en double

### Constat (export)
La règle dit *« numéro de table unique **dans son centre** »*, tous concours confondus. Il faut donc grouper par **(centre, numéro)**, pas par (concours, centre, numéro). Ce second regroupement cache les collisions entre concours.

| Centre | Numéro | Lignes | Concours concernés | Nature |
|---|---|:---:|---|---|
| L | L-0298 | 6 | IMPOTS | 6 candidats différents |
| L | L-0297 | 5 | IMPOTS | 5 candidats différents |
| C | C-3305 | 3 | DOUANES | 2 candidats, dont un inscrit 2 fois |
| C | C-3306 | 3 | **DOUANES + IMPOTS** | 2 candidats, dont un inscrit 2 fois |
| C | C-3308 | 3 | **TRESOR + IMPOTS** | 2 candidats, dont un inscrit 2 fois |
| C | C-3311 | 3 | **DOUANES + TRESOR** | 2 candidats, dont un inscrit 2 fois |
| C | C-3313 | 3 | DOUANES | 2 candidats, dont un inscrit 2 fois |
| P | **P-0464** | 2 | DOUANES | 2 candidats différents (cas signalé) |
| C | C-3309 | 2 | TRESOR | **le même candidat 2 fois**, donc INC-203 |
| N | N-0574 | 2 | DOUANES | **le même candidat 2 fois**, donc INC-203 |

**10 numéros en double, portés par 32 lignes.** **8** d'entre eux sont partagés par des candidats différents (le vrai INC-201). Les 2 autres sont des doubles inscriptions (INC-203).

### Dossier technique
Étape 6 : *« plus grand numéro du centre + 1 »*. Ce calcul est fait **avant** l'étape 7 (appel au service d'identification) et l'enregistrement n'a lieu qu'à l'étape 8. Rien ne verrouille la lecture et aucun index unique n'existe sur (centre, numéro).

### Journal
P-0464, le 19/11 :

| Requête | NPI | Arrivée (UTC) | Durée | Fin |
|---|---|---|---|---|
| `a93cfec6` | 7984581920 | 08:21:14.000 | 33 432 ms | 08:21:47 |
| `a061413f` | 3076016910 | 08:21:16.300 | 22 781 ms | 08:21:39 |

Les deux requêtes ont lu « plus grand numéro de Parakou = P-0463 » à 2 s d'intervalle. Elles ont ensuite attendu 22 à 33 s le service d'identification (ligne `WARN … (22766 ms)` du sujet), et chacune a enregistré P-0464.

### Cause racine
Un numéro calculé par **lecture puis écriture différée**, sans verrou ni contrainte d'unicité. La fenêtre entre la lecture et l'écriture vaut la durée de l'appel au service d'identification.

---

## C. INC-202 — Dépassement de capacité à Lokossa

### Constat (export)

| Centre | Capacité | Inscrits | Dépassement |
| :--- | :---: | :---: | :---: |
| **L (Lokossa)** | 300 | 307 | **+7** |

### Dossier technique
Étape 5 : *« refus si le nombre d'inscriptions du centre atteint sa capacité »*. C'est un `COUNT` lu sans verrou, suivi d'un enregistrement une à deux étapes plus loin. La base n'a pas de compteur ni de contrainte.

### Journal
Le 19/11, Lokossa compte 296 inscrits, soit **4 places libres**. **11 inscriptions** arrivent en 50 secondes, et chacune attend ensuite 20 à 62 s le service d'identification :

| Arrivée (UTC) | Requête | Durée | Numéro reçu |
|---|---|---|---|
| 08:11:01.871 | `aaf0f8db` | 21 824 ms | L-0297 |
| 08:11:07.847 | `29c31296` | 20 290 ms | L-0297 |
| 08:11:11.145 | `fd92dc93` | 26 708 ms | L-0297 |
| 08:11:16.244 | `036e0cc8` | 37 757 ms | L-0297 |
| 08:11:22.658 | `f4cf0482` | 61 746 ms | L-0297 |
| 08:11:26.471 | `160e4365` | 47 597 ms | L-0298 |
| 08:11:32.514 | `ca41610c` | 19 909 ms | L-0298 |
| 08:11:36.417 | `5239eb06` | 61 508 ms | L-0298 |
| 08:11:42.659 | `fd3154d6` | 37 407 ms | L-0298 |
| 08:11:47.322 | `0af7789b` | 47 680 ms | L-0298 |
| 08:11:51.081 | `baaa5823` | 52 289 ms | L-0298 |

La première de ces inscriptions n'est enregistrée qu'à 08:11:23. Les 11 avaient donc **toutes compté moins de 300 inscrits** au moment du contrôle. Les candidats arrivés ensuite, entre 08:11:57 et 08:12:16, sont bien refusés (« Ce centre d'examen est complet », 5 refus).

### Cause racine
La même que pour INC-201 : un contrôle de capacité par **lecture puis écriture différée**, sans verrou ni contrainte. Ce sont les **mêmes 11 requêtes** qui produisent à la fois le dépassement (INC-202) et L-0297 / L-0298 (INC-201).

---

## D. INC-203 — Doubles inscriptions (double clic)

### Constat (export) et journal

| NPI | Concours | Centre | 1ʳᵉ arrivée → 2ᵉ arrivée (UTC) | Écart | Adresse IP | Durées |
|---|---|---|---|---|---|---|
| 2937739971 | DOUANES | N | **18/11** 15:42:07.318 → 07.498 | 0,2 s | 41.138.94.37 | 258 / 279 ms |
| 2256599771 | DOUANES | C | 19/11 08:13:14.679 → 08:13:27.089 | 12 s | 41.138.81.11 | 27 / 51 s |
| 8869803777 | IMPOTS | C | 08:17:14.201 → 08:17:23.617 | 9 s | 105.235.11.7 | 26 / 44 s |
| 7586455716 | IMPOTS | C | 08:21:25.131 → 08:21:38.377 | 13 s | 41.138.87.11 | 58 / 59 s |
| 0751839491 | TRESOR | C | 08:25:02.910 → 08:25:11.205 | 8 s | 41.138.88.11 | 45 / 40 s |
| 9166289394 | TRESOR | C | 08:29:08.197 → 08:29:14.589 | 6 s | 105.235.11.66 | 47 / 40 s |
| 7586673329 | DOUANES | C | 08:33:19.999 → 08:33:33.425 | 13 s | 197.234.205.48 | 18 / 34 s |

L'écart se calcule **entre les heures d'arrivée**, pas entre les `cree_le`. Ceux-ci sont des heures de fin, qui peuvent s'inverser. Pour 9166289394, c'est la requête **arrivée en second** qui a été enregistrée la première.

**Lecture** : 6 doublons sur 7 ont lieu pendant la lenteur du 19/11. À chaque fois, c'est la **même adresse IP**, avec un second envoi 6 à 13 s après le premier, **pendant que le premier attend encore**. C'est le signalement du candidat : *« la page ne répondait pas : j'ai cliqué une seconde fois »*. Le 7ᵉ (18/11, N-0574) est un double clic **sans aucune lenteur** : deux envois à 0,2 s d'écart.

### Dossier technique
Étape 4 : *« refus si une inscription existe déjà pour ce NPI et ce concours »*. C'est une lecture sans verrou. La première requête n'est pas encore enregistrée quand la seconde fait son contrôle, et aucune contrainte UNIQUE n'existe sur (npi, concours).

### Cause racine
Un contrôle de doublon par **lecture puis écriture différée**, sans contrainte UNIQUE, et **rien contre le double envoi** : bouton toujours actif, aucun rejeu sûr de la même demande. Le cas du 18/11 prouve que ce défaut existe **même sans lenteur**. La lenteur du 19/11 a seulement multiplié les occasions.

---

## E. INC-204 — Clôture du Trésor une heure trop tôt

### Constat (export)

| Code | `cloture` stockée | Signification | Type de colonne |
| :--- | :--- | :--- | :--- |
| **TRESOR** | 2026-11-20 22:59:00 | UTC, soit **23:59 heure du Bénin** | `timestamp without time zone` ⚠️ |

La valeur stockée est **correcte**.

### Dossier technique
- *« un seul serveur d'application **réglé sur l'heure du Bénin** »* ;
- *« les instants (cloture…) y sont enregistrés **en UTC** »* ;
- étape 2 : *« refus si l'**heure courante du serveur** est postérieure à concours.cloture »*.

Le code compare donc une **heure locale du Bénin** à une **valeur UTC**, sans fuseau des deux côtés (colonne `without time zone`). À 22 h 59 au Bénin, le serveur lit « 22:59 » et conclut que la clôture `22:59:00` est atteinte. Il ferme ainsi **une heure trop tôt**.

### Journal
- premier refus « Inscriptions closes pour ce concours. » pour le Trésor : **2026-11-20T21:59:05Z**, soit 22:59:05 au Bénin. C'est le signalement du support ;
- entre 21:59:00 et 22:59:00 UTC : **94 candidats** refusés à tort, qui **ne se sont jamais inscrits ensuite** ;
- après 22:59:00 UTC, les refus sont normaux.

### Cause racine
**Une comparaison d'heures sans fuseau** entre l'horloge locale du serveur (GMT+1) et une valeur UTC. La donnée est juste, c'est la comparaison qui est fausse.

---

## F. INC-205 — Faux refus pour l'âge

### Dossier technique
Étape 3 : *« nombre de jours entre la date de naissance et le 31 décembre de l'année du concours, **divisé par 365** ; refus si le résultat **dépasse 35** »*.

Il y a deux erreurs dans cette formule :
1. elle **compte les fractions d'année**. Un candidat né le 20/06/1991 obtient 35,5 ans, ce qui est > 35, alors qu'il a **35 ans révolus** au 31/12/2026 ;
2. elle **ignore les années bissextiles**, ce qui fait 9 jours de décalage sur 35 ans.

Avec cette formule, est refusé tout candidat **né avant le 09/01/1992**. La bonne règle (au plus 35 ans révolus au 31/12/2026) ne refuse que ceux **nés avant le 01/01/1991**. Toute personne née entre le 01/01/1991 et le 08/01/1992 est donc refusée à tort.

### Journal : l'impact réel
| Indicateur | Valeur |
|---|---|
| Refus pour l'âge (« Âge limite dépassé ») | **78** |
| dont refus **à tort**, jamais inscrits ensuite | **36** |
| … nés en 1991 (35 ans) | 34, dont le candidat signalé, né le 20/06/1991 |
| … nés le **01/01/1992** et le **08/01/1992** (**34 ans**) | 2 : la preuve de l'erreur liée aux années bissextiles |

> L'ancien chiffre « 727 faux positifs » vient de l'application de la formule à **toute la table `candidats`** (908 contre 181). Or cette table contient surtout les candidats des **campagnes précédentes** (13 400 sur 19 303), et **aucune** de ces 908 personnes n'est inscrite en 2026. C'est une **exposition potentielle**, pas un nombre de candidats refusés. L'impact réel se lit dans le journal : **36**.

### Cause racine
**Une règle métier mal traduite en code** : un âge calculé en jours / 365 au lieu d'un âge révolu.

---

## G. INC-206 — Pages bloquées le 19/11 au matin

### Dossier technique
- le service d'identification est appelé *« avec un client HTTP standard, **dans sa configuration par défaut** »*. Or la configuration par défaut d'un client HTTP standard n'a **aucun délai d'attente** : l'appel attend aussi longtemps que le service le fait attendre ;
- la règle *« au-delà de 5 s, inscription en attente de vérification »* n'est donc **jamais appliquée** ;
- la **convocation rappelle le service** à chaque affichage, alors que nom et prénoms sont déjà dans `candidats`.

### Journal
| Indicateur | Valeur |
|---|---|
| Période | **19/11, de 08:09:48 à 08:39:49 UTC** (09 h 09 à 09 h 39 au Bénin), soit 30 min |
| Appels au service d'identification | **60, tous en WARN (≥ 5 s)** ; médiane 37,7 s, maximum **61,7 s** |
| Temps normal du service | 0,2 à 0,4 s, soit **100 à 150 fois plus lent** pendant l'incident |
| Inscriptions (`POST /api/inscriptions`) | 41 sur 46 au-dessus de 5 s, en moyenne **34,4 s** |
| Convocations | **18 sur 18** au-dessus de 5 s, en moyenne **38,9 s**, maximum 60,8 s |
| Pages qui n'appellent pas le service (`/api/centres`, `/api/concours`) | 32 requêtes, **toutes en moins de 40 ms** |
| Erreurs 5xx | aucune : les pages **attendaient**, elles ne plantaient pas |

Le serveur lui-même est resté sain. Seules les pages qui appellent le service d'identification étaient bloquées : **l'inscription et la convocation**, exactement les deux pages citées par l'exploitation.

### Cause racine
**Un appel externe sans délai d'attente**, placé sur deux chemins critiques (l'inscription, et la convocation qui n'en a pas besoin). Le déclencheur est externe (lenteur du service national, cause à demander à son opérateur). Le défaut est interne.

---

## H. INC-207 — Liste de Cotonou en plus de 40 s

### Dossier technique
- *« lit les inscriptions du centre et du concours, puis, **pour chacune**, le candidat correspondant dans candidats »* : **une requête par inscrit** (problème dit « N+1 »). Pour Cotonou (4 187 inscrits), cela fait environ 4 188 requêtes ;
- **aucun index** sur `candidats.npi` : chaque requête parcourt toute la table ;
- `candidats` *« conserve aussi les candidats des campagnes précédentes »* : la table compte 19 303 lignes, dont 13 400 de 2025.

### Journal
La durée **croît avec le nombre d'inscrits du centre** :

| Centre | Inscrits | Durée de la liste |
|---|---|---|
| Lokossa | ≈ 300 | **14 ms** |
| Parakou | ≈ 600 | 1,2 à 6,6 s |
| Cotonou | ≈ 4 200 | 18 appels : médiane 17,7 s, **maximum 46,5 s**, 3 au-dessus de 40 s |

### Cause racine
**Une requête par inscrit, multipliée par un parcours complet de `candidats` à chaque fois**, faute d'index. Le coût est donc proportionnel à « nombre d'inscrits × taille de `candidats` ». L'exigence est *« moins de 2 s avec 5 000 inscrits »*.

---

## I. INC-208 — Deux concours le même jour : **pas une anomalie**

| Code | `date_epreuve` |
| :--- | :--- |
| **DOUANES** | 2026-12-12 |
| **IMPOTS** | 2026-12-12 |
| **TRESOR** | 2026-12-19 |

La règle dit : *« il ne peut pas s'inscrire à deux concours dont les épreuves ont lieu le même jour »*. Douanes et Impôts ont lieu tous deux le 12/12. Le journal montre **3 refus** « Vous êtes déjà inscrit à un concours dont l'épreuve a lieu le même jour », tous corrects.

Le sujet le dit : *« Un comportement qui les respecte n'est pas une anomalie, même s'il est signalé. »* **Aucune correction ne doit être faite.** Il faut seulement répondre au candidat en lui rappelant la règle.

---

## J. Synthèse : les causes racines

| Incident | Défaut | Étape du dossier | Preuve dans le journal |
|---|---|---|---|
| INC-201 | **A + E** | étape 6 « max + 1 », avant l'étape 7, sans contrainte UNIQUE | P-0464 : 2 requêtes arrivées à 2 s d'écart, 22 et 33 s d'attente |
| INC-202 | **A + E** | étape 5 « COUNT », avant l'étape 7, sans contrainte | 11 arrivées à Lokossa en 50 s pour 4 places |
| INC-203 | **A + E + F** | étape 4, sans UNIQUE ; rien contre le double envoi | même IP, 2ᵉ envoi 6 à 13 s après ; N-0574 à 0,2 s sans lenteur |
| INC-204 | **C** | étape 2 : « heure courante du serveur » (Bénin) comparée à une valeur UTC | premier refus à 21:59:05 UTC ; 94 refusés à tort |
| INC-205 | **D** | étape 3 : jours / 365 | 78 refus, dont 36 à tort (dont 2 personnes de 34 ans) |
| INC-206 | **B** | client HTTP par défaut, sans délai ; convocation qui rappelle le service | 60 WARN de 08:09 à 08:39, jusqu'à 61,7 s ; autres pages en moins de 40 ms |
| INC-207 | **G + E** | « pour chacune, le candidat… », sans index, table des anciennes campagnes | 14 ms à Lokossa, 46,5 s à Cotonou |
| INC-208 | aucun | règle respectée | 3 refus corrects |

**Les défauts structurels**

| Défaut | Description |
|---|---|
| **A** | Contrôles en « **lire puis écrire différé** » (étapes 4, 5, 6), séparés de l'écriture (étape 8) par un appel externe (étape 7) |
| **B** | **Appel externe sans délai d'attente** (client HTTP par défaut), sur l'inscription et sur la convocation |
| **C** | **Comparaison d'heures sans fuseau** (serveur à l'heure du Bénin, valeur en UTC, colonne `without time zone`) |
| **D** | **Règle d'âge mal traduite** (jours / 365 au lieu de l'âge révolu) |
| **E** | **Aucune contrainte ni index en base** (0 UNIQUE, 0 CHECK, 0 index secondaire) |
| **F** | **Aucune protection contre le double envoi** (interface et API) |
| **G** | **Requête par ligne** (N+1) pour la liste des inscrits, sur une table qui garde toutes les campagnes |

---

## K. Les liens entre incidents

### 1. INC-206 a déclenché INC-201, INC-202 et INC-203

```
                    Défaut B : appel au service d'identification SANS délai d'attente
                                            │
           19/11 08:09 → 08:39 UTC : le service répond en 20 à 61 s au lieu de 0,3 s
                                            │
              ┌─────────────────────────────┴─────────────────────────────┐
              ▼                                                           ▼
   INC-206 : inscription et convocation                 Défaut A : la fenêtre entre la lecture
   bloquées de 30 à 60 s                                (étapes 4-5-6) et l'écriture (étape 8)
              │                                          passe de 0,3 s à 20-60 s
              │ « la page ne répondait pas »                   │  + Défaut E : aucune contrainte
              ▼                                                 │    pour rattraper l'erreur
   le candidat clique à nouveau ──────────┐          ┌──────────┴────────────┐
                                          ▼          ▼                       ▼
                                   INC-203 :     INC-201 :              INC-202 :
                                   6 doubles     8 numéros partagés     Lokossa 307 / 300
                                   inscriptions  (L-0297 ×5, L-0298 ×6, (les mêmes 11 requêtes
                                                  P-0464, Cotonou)       que L-0297 / L-0298)
```

**La preuve est dans le journal** : tous les numéros en double et 6 doubles inscriptions sur 7 se produisent **entre 08:11 et 08:34 UTC le 19/11**, pendant les 60 lignes WARN. Avant et après, la même concurrence existait, mais elle ne durait que 0,3 s et ne produisait presque rien.

**Les défauts A et E étaient latents**, et le défaut B les a révélés. Le cas N-0574 du 18/11 (double clic à 0,2 s, sans lenteur) le confirme : le défaut existait déjà. Il suffisait de deux clics assez rapprochés.

### 2. INC-201 et INC-202 sont un seul et même événement à Lokossa
Les 11 requêtes arrivées entre 08:11:01 et 08:11:51 produisent **à la fois** le dépassement (307 / 300) et les numéros L-0297 ×5 et L-0298 ×6. Elles ont lu le même `COUNT` et le même « max + 1 ».

### 3. INC-203 et INC-201 se recouvrent
Une double inscription donne aussi un **numéro en double** (C-3309, N-0574). Il faut donc les distinguer quand on compte : 8 numéros partagés par des candidats différents, et 2 numéros dus à des doubles inscriptions.

### 4. INC-204 et INC-205 : deux règles mal traduites en code
Ces deux incidents sont **indépendants de la charge et de la lenteur**. Ce sont deux règles écrites correctement dans le sujet mais mal codées (le fuseau horaire pour l'un, la formule d'âge pour l'autre). Ils touchent tous deux des candidats **refusés à tort qui ne se sont jamais inscrits ensuite** (94 et 36).

### 5. INC-207 et la conservation des anciennes campagnes
La table `candidats` garde 13 400 personnes de 2025, qui n'ont rien à faire dans la campagne en cours. Sans index, chaque recherche de candidat parcourt aussi ces lignes. Ce même choix **aggrave la fuite de données** de l'incident non signalé du 20/11 : une injection SQL sur la recherche par nom a extrait **18 535 candidats**, dont 13 400 de la campagne précédente.

### 6. INC-208 n'est lié à aucun défaut
C'est la règle qui fonctionne. Ce cas sert de **contrôle** : la règle du même jour est bien appliquée en temps normal (3 refus corrects). Mais faute de contrainte en base (défaut E), elle pourrait elle aussi être contournée par des requêtes simultanées, comme INC-203.

---

## L. Priorités de correction

1. **Défaut E puis A, d'abord dans la base** : index uniques (centre, numéro), (npi, concours) et (npi, date d'épreuve), plus un compteur de capacité incrémenté de façon atomique. C'est la **seule** protection qui tient face à des requêtes simultanées, quelle que soit la lenteur.
2. **Défaut B** : délai d'attente de 5 s au total sur l'appel au service, statut « en attente de vérification » au-delà, appel placé hors du verrou, et convocation lue dans `candidats`.
3. **Défaut F** : bouton désactivé après le clic, et API qui renvoie la même inscription en cas de nouvel envoi.
4. **Défauts C et D** : comparer des instants avec fuseau, calculer l'âge révolu, et recontacter les **94 + 36** candidats refusés à tort.
5. **Défaut G** : une seule requête pour lire les candidats d'une liste, un index sur `candidats.npi`, et sortir les anciennes campagnes de la table active.
