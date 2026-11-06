# Rapport d'incident — INC-206

**Pages bloquées pendant la lenteur du service d'identification (19 novembre 2026)**

| | |
|---|---|
| Signalé par | Exploitation |
| Signalement | « Le 19 novembre au matin, pendant une demi-heure, plus personne ne pouvait s'inscrire ni consulter sa convocation : les pages tournaient sans fin. » |
| Date | 19/11/2026, de 09 h 09 à 09 h 39, heure du Bénin (08:09:48 → 08:39:49 UTC) |
| Durée | 30 minutes |
| Gravité | Majeure : service dégradé en pleine campagne, et données corrompues |
| Incidents liés | INC-201 (numéro P-0464 en double), INC-202 (Lokossa à 307 inscrits pour 300 places), INC-203 (doubles convocations) : **tous causés par cette même demi-heure** |
| Sources | `journal_production.log` (18/11 00:00 → 21/11 07:00 UTC, 8 221 requêtes, 4 556 appels au service d'identification) ; `base_inscriptions.sql` (export du 21/11, 08 h 00) |

---

## 1. Résumé

Pendant 30 minutes, le service national d'identification a répondu en 20 à 60 secondes au lieu de 0,2 à 0,4 seconde. L'application l'appelait sans délai d'attente, et elle l'appelait à deux endroits : à chaque inscription et à chaque affichage de convocation. Ces deux pages ont donc attendu en moyenne 35 à 40 secondes. Les autres pages sont restées rapides.

Les inscriptions lentes avaient déjà fait leurs contrôles de capacité et calculé leur numéro de table *avant* l'appel. Elles se sont donc chevauchées, ce qui a produit trois anomalies :

- des numéros de table attribués plusieurs fois ;
- un centre au-delà de sa capacité ;
- des doubles inscriptions, quand les candidats ont recliqué sur « Valider ».

---

## 2. Chronologie

Heures UTC (heure du Bénin = UTC + 1).

| Heure UTC | Événement | Source |
|---|---|---|
| 19/11, jusqu'à 08:05 | Fonctionnement normal : appels au service d'identification en 200 à 600 ms | journal |
| **08:09:48** | Début du premier appel lent (`req:e92a500f`, 5 157 ms) | journal, WARN |
| 08:10 → 08:15 | Les durées explosent : médiane 37,7 s, maximum 61,7 s | journal |
| 08:11:01 → 08:11:51 | 11 inscriptions au centre de Lokossa démarrent alors qu'il reste 4 places. Toutes passent le contrôle de capacité puis attendent le service | journal (heure d'arrivée = horodatage − durée) |
| 08:11:23 → 08:12:43 | Les 11 sont enregistrées : 5 fois **L-0297**, 6 fois **L-0298**. Le centre passe à **307 / 300** (INC-202) | journal, export |
| 08:11:57 → 08:12:16 | 5 candidats arrivés ensuite sont refusés « centre complet », à juste titre | journal |
| 08:13 → 08:34 | Même phénomène à Cotonou (6 numéros en double) et à Parakou (**P-0464**, INC-201). 6 candidats recliquent sur « Valider » et obtiennent deux inscriptions (INC-203) | journal, export |
| 08:21:39 / 08:21:47 | P-0464 attribué deux fois : `a061413f` (22,8 s) et `a93cfec6` (33,4 s) | journal |
| **08:39:49** | Fin du dernier appel lent (40,4 s) | journal, WARN |
| 08:40 → 08:45 | Retour à la normale (moins de 4 s, puis environ 300 ms) | journal |
| 19/11 → 21/11 | Signalements INC-201, INC-202, INC-203 et INC-206 | registre des incidents |

**Détection.** Le journal contenait 60 lignes WARN (« appel identite ≥ 5 s »), mais aucune alerte ne s'est déclenchée. L'incident a été connu par les signalements, pas par la supervision.

---

## 3. Cause racine

**Déclencheur, externe :** un ralentissement du service national d'identification, de 08:09 à 08:39 UTC. Sa cause est à demander à l'opérateur de ce service. Il n'y a eu aucune erreur, seulement de la lenteur : toutes les réponses sont des 200 ou des 404.

**Causes racines, internes :** quatre défauts de l'application ont transformé une lenteur externe en panne visible et en données fausses.

1. **Aucun délai d'attente sur l'appel au service d'identification.** Le client HTTP est utilisé « dans sa configuration par défaut », et celle-ci n'a pas de délai. La règle « au-delà de 5 s, inscription en attente de vérification » n'était donc jamais appliquée : on a attendu jusqu'à 61,7 s.
2. **La convocation rappelait le service à chaque affichage**, alors que nom et prénoms sont déjà dans `candidats`. Une page en lecture seule dépendait donc d'un service externe.
3. **Inscription en « lire puis écrire », sans verrou ni contrainte.** Les étapes 5 (comptage des inscrits) et 6 (plus grand numéro + 1) sont faites *avant* l'appel au service (étape 7). L'enregistrement (étape 8) n'a lieu qu'après. Pendant les 20 à 60 s d'attente, d'autres inscriptions lisent le même compteur et le même numéro. La base n'avait **aucune contrainte d'unicité** (« clés primaires uniquement ») pour s'y opposer.
4. **Rien ne protège contre le double envoi.** Le bouton reste actif, aucune requête n'est rejouée de façon sûre, et `(npi, concours)` n'est pas unique. Le même défaut a d'ailleurs produit un double clic le 18/11 à 15:42, sans aucune lenteur : N-0574, deux POST à 200 ms d'écart.

En bref : cette concurrence existait déjà, mais en temps normal la fenêtre durait 0,3 s et les chevauchements étaient rares. La lenteur l'a portée à 20 à 60 s, et 30 minutes ont suffi à produire les doublons.

---

## 4. Impact chiffré

### Disponibilité, du 19/11 08:09:48 au 08:39:49 UTC

| Page | Requêtes | Dont plus de 5 s | Durée moyenne | Maximum |
|---|---|---|---|---|
| Inscription (`POST /api/inscriptions`) | 46 | **41** | **34,4 s** | 61,7 s |
| Convocation (`GET …/convocation`) | 18 | **18 (100 %)** | **38,9 s** | 60,8 s |
| Listes des centres et concours | 32 | 0 | moins de 40 ms | 39 ms |
| Appels au service d'identification | 60 | **60 (100 %, WARN)** | médiane 37,7 s | 61,7 s |

- Temps normal du service : environ 200 à 400 ms. Pendant l'incident, il était **100 à 150 fois plus lent**.
- Aucune erreur 5xx : les pages ne « plantaient » pas, elles attendaient. Le journal ne voit que les requêtes terminées. Les candidats qui ont fermé leur page avant la fin n'y apparaissent pas, donc **l'abandon réel n'est pas mesurable**.
- Le serveur lui-même est resté sain : les pages qui n'appellent pas le service répondaient en moins de 40 ms.

### Données (export du 21/11)

| Conséquence | Chiffre |
|---|---|
| Numéros de table attribués plusieurs fois (INC-201) | **9 numéros**, portés par **30 inscriptions** : L-0297 ×5, L-0298 ×6, P-0464 ×2, et 6 numéros à Cotonou |
| Dépassement de capacité (INC-202) | Lokossa : **307 inscrits pour 300 places**, soit **7 candidats** sans place |
| Doubles inscriptions (INC-203) | **6** pendant l'incident, plus 1 le 18/11 (N-0574) : **7 candidats avec deux convocations** |
| Numéros à changer après réparation | **16 inscriptions** : 9 nouvelles convocations définitives, plus 7 numéros provisoires à Lokossa en attente de décision |

### Personnes touchées

- **22 candidats** à recontacter : 9 changent de numéro, 7 avaient deux convocations, 7 sont au-delà de la capacité de Lokossa. Un même candidat de Cotonou figure dans deux de ces groupes.
- **59 requêtes** ont attendu de 5 à 62 s : 41 inscriptions et 18 convocations. Les 5 refus « centre complet » de Lokossa ont été instantanés, car ils n'appellent pas le service.
- 4 chefs de centre (Lokossa, Cotonou, Parakou, Porto-Novo) ont reçu des listes à reprendre.

---

## 5. Correction

### 5.1 Code (application Django)

| Correction | Fichier |
|---|---|
| L'appel au service d'identification ne dure **jamais plus de 5 s au total**, connexion et lecture comprises. Il est coupé à 5 004 ms même si le service répond octet par octet. Au-delà, l'inscription est enregistrée **« en attente de vérification »** | `test1/services/identite_client.py` |
| L'appel se fait **avant** la transaction, et la ligne du centre n'est jamais verrouillée pendant l'attente | `test1/services/inscription_service.py` |
| Capacité et numéro sont réservés en **un seul `UPDATE` atomique** (`inscrits < capacite`) | `inscription_service.py` |
| Index uniques `(centre, numero_table)` et `(npi, date_epreuve)`. Un double clic renvoie la **même** inscription (réponse 200) | `test1/models/inscriptions.py`, migration 0004 |
| La convocation lit `candidats` et **n'appelle plus le service** | `test1/views/inscription_view.py` |

### 5.2 Données

Le script `reparation/reparer_export.sql` peut être rejoué sans risque et s'exécute en une seule transaction :

- **7 doublons** sont archivés puis supprimés. On garde à chaque fois la requête arrivée la première.
- **Les numéros en double sont réattribués** selon la règle du « premier arrivé », reconstituée depuis le journal.
- **À Lokossa, rien n'est supprimé.** Les 7 candidats au-delà de la capacité sont listés dans `decision_capacite` pour décision.
- **Des contraintes empêchent la répétition** : numéros uniques, inscription unique, pas deux concours le même jour, et une capacité tenue par la base (trigger).

### 5.3 Vérification

Tests automatisés :

- `reparation/test_reparation.py` : **15 tests passés** sur PostgreSQL. Ils vérifient la réparation et le fait que la rejouer ne change rien. Ils vérifient aussi que la base refuse un doublon et respecte la capacité quand 10 connexions simultanées visent 3 places : 3 acceptées, 7 refusées.
- `test1/tests/test_inscriptions.py` : délai de 5 s du service d'identification (passés), et 40 inscriptions simultanées pour 20 places. Ces derniers n'ont pas encore tourné : la base de test Django reste à créer.

---

## 6. Actions pour éviter que l'incident se reproduise

| # | Action | Responsable proposé | Échéance |
|---|---|---|---|
| 1 | Déployer les corrections du code (délai de 5 s, statut « en attente », réservation atomique, convocation sans appel externe) | Équipe de développement | Avant la clôture DOUANES / IMPOTS (30/11) |
| 2 | Appliquer `reparer_export.sql` en production, avec sauvegarde avant et pendant une fenêtre de maintenance | Exploitation | Dès validation |
| 3 | **Alerte de supervision** : plus de 3 appels au service d'identification au-dessus de 5 s en 5 minutes, ou délai p95 au-dessus de 2 s | Exploitation | 1 semaine |
| 4 | Tâche de **re-vérification** des inscriptions « en attente de vérification », avec relance automatique et suivi | Équipe de développement | Avec l'action 1 |
| 5 | **Coupe-circuit** : après N délais dépassés, ne plus appeler le service pendant 30 s et passer directement en « en attente » | Équipe de développement | 2 semaines |
| 6 | Interface : **désactiver « Valider » après le clic** et afficher « inscription en cours » | Équipe de développement (front) | Avec l'action 1 |
| 7 | Demander à l'opérateur du service d'identification la **cause du ralentissement** et un engagement de délai de réponse | Direction des concours | 1 semaine |
| 8 | Journaliser aussi l'**heure d'arrivée** des requêtes. Il a fallu la reconstituer (fin moins durée) pour départager les candidats | Équipe de développement | 2 semaines |
| 9 | **Test de charge** reproduisant un service d'identification lent (30 s) avec des inscriptions simultanées, joué à chaque version | Équipe de développement | Avant la prochaine campagne |
| 10 | Mettre en place une procédure d'incident (« service d'identification lent ») : qui prévenir, comment vérifier les doublons, comment réparer | Exploitation et Direction | 1 mois |

### Décisions et communications en attente

- **Direction des concours** : décider du sort des 7 inscrits de Lokossa (L-0301 à L-0307) : augmenter la capacité, les transférer, ou annuler. Il est recommandé de ne pas annuler, puisque leur inscription leur a été confirmée.
- **Candidats** : nouvelles convocations pour les 9 changements de numéro, et message « une seule convocation valable » pour les 7 doubles inscriptions. Liste dans la vue `reparation_a_prevenir`.
- **Chefs de centre** de Lokossa, Cotonou, Parakou et Porto-Novo : nouvelles listes d'émargement.

---

## 7. Hors du périmètre de cet incident, relevé pendant l'analyse

- **Sécurité (à traiter en priorité).** Le 20/11 à 03:13 UTC, `GET /api/inscrits/recherche?nom='` renvoie une erreur de syntaxe SQL (`unterminated quoted string`). La recherche par nom est vulnérable à une **injection SQL**. Prévenir le responsable sécurité. La version corrigée utilise l'ORM Django, qui paramètre les requêtes.
- **INC-204 et INC-205.** D'après le journal, 94 candidats ont été refusés à tort à la clôture du Trésor, et 36 sur le critère d'âge. Ils sont à traiter dans leurs propres rapports.
