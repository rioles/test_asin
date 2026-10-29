# INTERVENTION.md – Priorisation des incidents

Classement établi **avant toute analyse détaillée**, à partir des signalements, du dossier technique et des règles de fonctionnement attendu.

**Critères (par ordre d'importance) :** étendue de l'impact, irréversibilité du préjudice, permanence du bug, effort de correction.

| Rang | Incident | Justification en une ligne |
|------|----------|----------------------------|
| 1 | **INC-206** – Pages bloquées pendant 30 min | Panne totale (inscription et convocation) pour tous les candidats, due à un appel au service d'identification sans timeout, qui peut se reproduire à tout moment et viole la règle des 5 secondes. |
| 2 | **INC-204** – « Inscriptions closes » dès 22 h 59 | Des candidats ont été exclus à tort pendant une heure, ce qui est irréversible et expose à des recours ; la clôture est probablement comparée à l'heure locale (GMT+1) au lieu de l'UTC, donc toutes les clôtures futures sont touchées. |
| 3 | **INC-205** – Refus à tort à 35 ans | Bug permanent et déterministe (jours / 365 ignore les années bissextiles) qui refuse tout candidat de 35 ans révolus tant qu'un concours est ouvert. |
| 4 | **INC-202** – Lokossa : 307 inscrits pour 300 places | Dépassement réel de capacité (course critique entre comptage et insertion) : des inscrits n'auront pas de place le jour de l'épreuve, avec un arbitrage métier à prévoir sur les 7 surnuméraires. |
| 5 | **INC-201** – Numéro de table P-0464 en double | Calcul `MAX + 1` sans verrou ni contrainte d'unicité : ambiguïté le jour de l'examen, mais réparable par renumérotation sans exclure personne. |
| 6 | **INC-203** – Double inscription par double clic | Même cause racine que 201 et 202 (aucune unicité en base) et en grande partie provoqué par 206 ; les doublons se suppriment facilement mais consomment des places. |
| 7 | **INC-207** – Liste de Cotonou > 40 s | Problème de performance sans perte de droits ni corruption de données (requêtes N+1 et absence d'index), corrigeable par un `JOIN` et des index. |
| 8 | **INC-208** – Impossible de s'inscrire à deux concours le même jour | Pas une anomalie : la règle de fonctionnement interdit explicitement cette double inscription, il suffit de vérifier les dates d'épreuve et de répondre au candidat. |

## Regroupements de correction

- **Chantier concurrence (202, 201, 203)** : transaction ou verrou par centre, contraintes `UNIQUE (npi, concours_id)` et `UNIQUE (centre_id, numero_table)`, puis nettoyage des données.
- **Chantier temps (204, 205)** : tout comparer en UTC et calculer l'âge en années révolues.
- **Chantier performance (207)** : jointure unique et index sur `inscriptions` et `candidats`.
