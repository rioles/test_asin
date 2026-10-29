# Rapport d'Audit et Bilan des Incidents TMA

Ce document synthétise les résultats de l'audit de la base de données, l'analyse détaillée des incidents identifiés lors de la campagne d'inscription, ainsi que la matrice des causes structurelles et des recommandations de correction.

---

## A. Schéma de la base (audit §0)

| Contrôle | Résultat |
| :--- | :--- |
| **Contraintes PRIMARY KEY** | 4 (une par table) |
| **Contraintes NOT NULL** | 20 |
| **Contraintes FOREIGN KEY** | 2 (`inscriptions.centre_id`, `inscriptions.concours_id`) |
| **Contraintes UNIQUE** | 0 ⚠️ |
| **Contraintes CHECK** | 0 ⚠️ |
| **Index secondaires** | 0 ⚠️ |
| **Type de `cloture`** | `timestamp without time zone` ⚠️ |

---

## B. INC-201 — Numéros en double (10)

| Concours | Centre | Numéro | Occurrences |
| :--- | :--- | :--- | :---: |
| IMPOTS | L | L-0298 | 6 |
| IMPOTS | L | L-0297 | 5 |
| DOUANES | C | C-3305 | 3 |
| DOUANES | C | C-3313 | 3 |
| DOUANES | N | N-0574 | 2 |
| DOUANES | P | P-0464 | 2 |
| IMPOTS | C | C-3306 | 2 |
| IMPOTS | C | C-3308 | 2 |
| TRESOR | C | C-3309 | 2 |
| TRESOR | C | C-3311 | 2 |

---

## C. INC-202 — Dépassement de capacité

| Centre | Capacité | Inscrits | Dépassement |
| :--- | :---: | :---: | :---: |
| **L (Lokossa)** | 300 | 307 | +7 |

---

## D. INC-203 — NPI en double (7)

| NPI | Concours | Occurrences | Écart entre soumissions |
| :--- | :--- | :---: | :---: |
| 2937739971 | DOUANES | 2 | 0 s |
| 9166289394 | TRESOR | 2 | 1 s |
| 0751839491 | TRESOR | 2 | 4 s |
| 7586455716 | IMPOTS | 2 | 15 s |
| 8869803777 | IMPOTS | 2 | 28 s |
| 7586673329 | DOUANES | 2 | 29 s |
| 2256599771 | DOUANES | 2 | 37 s |

---

## E. INC-204 — Clôture du Trésor

| Code | `cloture` (UTC) | `cloture` (Bénin) | Type de colonne |
| :--- | :--- | :--- | :--- |
| **TRESOR** | 2026-11-20 22:59:00 | 2026-11-20 23:59:00 | `timestamp without time zone` ⚠️ |

---

## F. INC-205 — Faux positifs d'âge

| Indicateur | Valeur |
| :--- | :---: |
| **Refus avec la formule `jours / 365 > 35`** | 908 |
| **Refus avec la bonne règle (`date < 1991-01-01`)** | 181 |
| **Nombre de faux positifs (candidats rejetés à tort)** | **727** |

---

## G. INC-208 — Dates d'épreuve

| Code | `date_epreuve` |
| :--- | :--- |
| **DOUANES** | 2026-12-12 |
| **IMPOTS** | 2026-12-12 |
| **TRESOR** | 2026-12-19 |

---

## Conclusion & Synthèse Technique

Les 8 incidents identifiés se réduisent à **5 défauts structurels** :

1. **Défaut E (Aucune contrainte en base)** — Multiplicateur des effets du défaut A, confirmé par l'audit SQL (`0 UNIQUE`, `0 CHECK`).
2. **Défaut A (Transactions non atomiques / Race Conditions)** — Produit `INC-201`, `INC-202`, `INC-203` (chiffré à 10 numéros en double, 1 centre en dépassement et 7 NPI en double).
3. **Défaut B (Appel HTTP externe dans la transaction)** — Produit `INC-206` et aggrave le défaut A (fenêtre de course multipliée par 1000 lors des ralentissements).
4. **Défaut C (Gestion erronée des fuseaux horaires)** — Produit `INC-204` ; la valeur enregistrée est correcte, mais la comparaison horaire applicative est fausse.
5. **Défaut D (Règles métier mal codées & absence d'indexation)** — Produit `INC-205` (727 faux positifs d'âge), `INC-207` (temps de réponse de 46 s par manque d'index), et `INC-208` (règle métier contestée mais conforme).

### Interdépendance des défauts :
- **A et E se cumulent** (cause directe du dépassement du centre de Lokossa) ;
- **B aggrave A** (génère des rafales de doublons pendant les lenteurs du service externe) ;
- **C est isolé** (problème d'alignement timezone serveur/DB) ;
- **D regroupe trois défauts indépendants** partageant une origine commune de codage métier.

> **Plan d'action prioritaire :**  
> La correction prioritaire est l'élimination du **Défaut E (Ajout des contraintes d'unicité et de contrôle en base de données)**. C'est le seul correctif garantissant une protection intégrale contre les accès concurrents (Défaut A) quelle que soit la charge système, et rendant les correctifs applicatifs incournables.