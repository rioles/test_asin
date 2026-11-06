# Incident non signalé : injection SQL et extraction de la table `candidats`

| | |
|---|---|
| Date | **20/11/2026, de 03:12:40 à 03:14:16 UTC** (04 h 12 à 04 h 14, heure du Bénin), soit 1 min 36 s |
| Origine | Adresse IP **102.64.217.33**, externe. Elle n'apparaît nulle part ailleurs dans le journal |
| Point d'entrée | `GET /api/inscrits/recherche?nom=…` (recherche par nom) |
| Détection | Personne. C'est la **seule ligne ERROR** des 3 jours de journal, et aucune alerte ne s'est déclenchée |
| Gravité | **Critique** : fuite de données personnelles de **18 535 personnes**, dont l'identifiant national (NPI) |
| Sources | `journal_production.log` (lignes `req:4fd4b53c`, `1e91b46a`, `578397d9`, `d1479185`, `5c783014`) et `base_inscriptions.sql` |

---

## 0. Pourquoi c'est l'incident « que personne n'a signalé »

Les huit incidents signalés (INC-201 à INC-208) portent sur des numéros de table, la capacité, les doubles convocations, la clôture, l'âge, la lenteur du 19/11, la liste de Cotonou et la règle du même jour. **Aucun ne concerne la recherche par nom, une erreur SQL ou une fuite de données.**

Ce qui explique que l'attaque soit passée inaperçue :
- elle a duré **1 min 36 s, à 4 h du matin** (heure du Bénin) ;
- **l'extraction elle-même est journalisée en `INFO … -> 200`**, comme une recherche réussie. Seule la requête de test (`nom='`) a produit une `ERROR` ;
- cette ligne est **la seule `ERROR` du journal** (12 716 INFO, 60 WARN, 1 ERROR) ;
- aucune alerte ne surveille les erreurs 500, ni le nombre de lignes renvoyées par une recherche (`lignes=18535` alors que la recherche est limitée à 50).

### Extrait du journal (lignes 7873 à 7877)

```
2026-11-20T03:12:40.580Z INFO  [req:4fd4b53c] 102.64.217.33 GET /api/inscrits/recherche?nom=KPADONOU -> 200 (88 ms) lignes=390
2026-11-20T03:13:05.084Z ERROR [req:1e91b46a] 102.64.217.33 GET /api/inscrits/recherche?nom=%27 -> 500 (75 ms) erreur="SQLSTATE[42601]: Syntax error: 7 ERROR:  unterminated quoted string at or near "'%' LIMIT 50""
2026-11-20T03:13:27.960Z INFO  [req:578397d9] 102.64.217.33 GET /api/inscrits/recherche?nom=%27%20OR%20%271%27%3D%271 -> 200 (1328 ms) lignes=50
2026-11-20T03:13:50.708Z INFO  [req:d1479185] 102.64.217.33 GET /api/inscrits/recherche?nom=%27%20UNION%20SELECT%20npi%2C%20nom%2C%20date_naissance%20FROM%20candidats%20-- -> 200 (1103 ms) lignes=18535
2026-11-20T03:14:16.689Z INFO  [req:5c783014] 102.64.217.33 GET /api/inscrits/recherche?nom=%27%20UNION%20SELECT%20npi%2C%20nom%2C%20date_naissance%20FROM%20candidats%20-- -> 200 (1061 ms) lignes=18535
```

Paramètre `nom` une fois décodé :

```
KPADONOU
'
' OR '1'='1
' UNION SELECT npi, nom, date_naissance FROM candidats --
' UNION SELECT npi, nom, date_naissance FROM candidats --
```

Requête reconstituée à partir du message d'erreur, telle que la base l'a exécutée lors de l'extraction :

```sql
SELECT … FROM candidats WHERE nom LIKE '' UNION SELECT npi, nom, date_naissance FROM candidats --%' LIMIT 50
--                                       └──────────── injecté ───────────────────────────┘ └ neutralisé ┘
```

---

## 1. Ce qui s'est passé

La recherche par nom construit sa requête SQL en **collant le texte saisi** dans la requête, du type `… WHERE nom LIKE '<saisie>%' LIMIT 50`. Le message d'erreur du journal le prouve : `unterminated quoted string at or near "'%' LIMIT 50"`. L'attaquant a suivi une progression classique, en cinq requêtes :

| Heure UTC | Requête (décodée) | Résultat | Ce que l'attaquant apprend |
|---|---|---|---|
| 03:12:40 | `nom=KPADONOU` | 200, 390 lignes | Repérage : la fonction répond depuis Internet, **sans authentification** |
| 03:13:05 | `nom='` | **500, erreur SQL** | Une apostrophe casse la requête : elle est injectable. Le message d'erreur révèle sa structure |
| 03:13:27 | `nom=' OR '1'='1` | 200, 50 lignes | La condition est contournée et la requête renvoie n'importe quelle ligne |
| 03:13:50 | `nom=' UNION SELECT npi, nom, date_naissance FROM candidats --` | 200, **18 535 lignes** | **Extraction de toute la table** : le `--` neutralise le `LIMIT 50` |
| 03:14:16 | même requête | 200, **18 535 lignes** | Seconde extraction, sans doute pour la sauvegarder |

**L'extraction est complète.** La base comptait exactement **18 535 candidats** à 03:13:50 (export : `cree_le` ≤ 20/11 03:13:50). Toute la table est sortie.

**La fonction n'aurait jamais dû être accessible depuis Internet.** En usage normal, une seule adresse l'appelle : l'adresse **interne 10.20.1.15**, six fois en 3 jours, toutes les 7 h 03. Cela ressemble à un outil interne ou à une tâche automatique.

---

## 2. Ce qui a pu être exposé

### Certain : prouvé par le journal

| Donnée | Nombre de personnes |
|---|---|
| **NPI** (numéro personnel d'identification national), **nom**, **date de naissance** | **18 535** |
| dont candidats des **campagnes précédentes (2025)**, conservés dans `candidats` | 13 400 (72 %) |
| dont personnes **sans aucune inscription** à un concours 2026 | 12 913 |
| Personnes nées entre le 22/02/1990 et le 30/06/2005 | toutes |
| Colonnes normales de la recherche, probablement NPI, nom et prénoms | 50 (requête `OR '1'='1`) |

### Pourquoi c'est grave
- **Le NPI est un identifiant national**, valable bien au-delà des concours. C'est lui qui sert à interroger le service national d'identification.
- **NPI et date de naissance sont exactement ce que demande le formulaire d'inscription.** Avec ces données, un tiers peut **inscrire une personne à sa place**. Il peut ainsi lui « prendre » son concours, puisqu'on ne peut pas s'inscrire à deux concours le même jour, ou occuper des places dans un centre. Il peut aussi lui envoyer des convocations ou des demandes de paiement frauduleuses, qui paraîtront crédibles.
- **Les données des campagnes précédentes n'avaient pas à être là** : 13 400 personnes sont exposées alors qu'elles ne participent pas à la campagne en cours.

### Possible, non prouvé par le journal
L'injection permet d'exécuter n'importe quelle lecture avec les droits du compte de base de données de l'application. Le journal ne montre que deux charges, mais l'attaquant aurait aussi pu lire :
- la table `inscriptions` : centre, concours, numéro de table ;
- les tables d'autres applications hébergées sur la même base ;
- des informations sur le serveur : version, utilisateurs, et selon les droits les empreintes de mots de passe.

Le format d'erreur `SQLSTATE[…]` est celui de PDO, l'interface base de données de PHP. Si la requête est exécutée sans paramètres, PostgreSQL accepte **plusieurs instructions à la suite**, ce qui permettrait de **modifier ou supprimer** des données.

**Ce que les données permettent d'exclure :**
- **aucune inscription fantôme** : les 2 007 inscriptions créées pendant la période du journal correspondent toutes à une requête `POST … 201` journalisée ;
- **pas d'abus visible après l'attaque** : aucune adresse n'a fait d'inscriptions ou de consultations de convocations en rafale. Le maximum est de 28 POST et 26 convocations par adresse, sur des adresses d'opérateurs partagées.

**Ce qu'on ne peut pas exclure :**
- une modification de `candidats` (nom ou date de naissance changés), faute de copie de référence ;
- une exploitation **antérieure au 18/11**, puisque le journal ne couvre que 3 jours alors que la faille existe depuis la mise en ligne ;
- l'usage des données hors de notre système : hameçonnage, usurpation d'identité.

---

## 3. Mesures immédiates (dans les 24 heures)

### Contenir
1. **Couper `/api/inscrits/recherche` depuis Internet, tout de suite.** Le limiter au réseau interne (10.20.0.0/16) au niveau du serveur web ou du pare-feu, ou le désactiver.
2. **Bloquer 102.64.217.33.** C'est utile mais insuffisant : l'attaquant peut changer d'adresse.
3. **Ne plus renvoyer les erreurs SQL au client.** L'erreur 500 a très probablement aidé l'attaquant. Il faut un message générique côté client et le détail uniquement dans le journal.

### Corriger
4. **Requête paramétrée** pour la recherche. La version Django corrigée utilise l'ORM (`nom__istartswith`), qui paramètre toujours la requête.
5. **Revoir le reste du code** pour toute autre requête construite par concaténation.
6. **Compte de base de données à droits minimaux** pour l'application : seulement les tables nécessaires, pas de propriété des tables, pas de superutilisateur. Ensuite, **changer son mot de passe**, au cas où l'attaquant aurait lu des informations de configuration.

### Préserver les preuves et mesurer l'étendue
7. **Copier et mettre sous scellé** le journal applicatif, les journaux du serveur web (tailles de réponse, user-agent), les journaux PostgreSQL et un instantané de la base.
8. **Récupérer les journaux antérieurs au 18/11** et y chercher d'autres charges d'injection (`'`, `UNION`, `OR`, `--`, `%27`) sur toutes les routes.
9. **Vérifier l'intégrité** : comparer `candidats` et `inscriptions` à la dernière sauvegarde d'avant le 20/11 à 03:12 UTC. Chercher dans les journaux PostgreSQL des `UPDATE`, `DELETE` ou `DDL` inhabituels.

### Surveiller
10. **Alerte sur les erreurs 500 et SQL**, et sur les recherches qui renvoient plus de 50 lignes. Une telle réponse est impossible en usage normal : en voir une, c'est le signe d'une attaque.
11. **Surveiller les inscriptions suspectes** jusqu'à la clôture du 30/11 : NPI de la campagne 2025 qui s'inscrivent soudainement, rafales depuis une même adresse, centre ou concours changés pour un candidat. Envisager un code de confirmation par SMS ou e-mail avant de valider une inscription.

### Prévenir
12. **Responsable sécurité (RSSI)** et **délégué à la protection des données (DPO)** : immédiatement.
13. **Direction des concours** : décision sur la communication et sur la surveillance des inscriptions.
14. **Autorité de protection des données personnelles (APDP)** : il s'agit d'une violation de données personnelles. Le DPO ou le juriste doit confirmer le délai et la forme de la notification exigés par la loi.
15. **Le CERT national (bjCSIRT)** et **l'opérateur du service national d'identification**, puisque des NPI ont fuité.
16. **Les 18 535 personnes concernées**, sous l'arbitrage du DPO et de la Direction. Message type : leurs NPI, nom et date de naissance ont été exposés ; l'organisateur ne demande jamais de paiement ni de code par téléphone ; vérifiez votre inscription sur le site officiel ; signalez toute convocation que vous n'avez pas demandée.

---

## 4. Ensuite (prochaines semaines)

- **Authentification** sur les fonctions réservées aux agents : recherche et listes des centres. Contrôle d'accès sur la convocation, consultable aujourd'hui avec un simple numéro d'inscription qui se suit (`/api/inscriptions/{id}/convocation`).
- **Minimisation et conservation** : sortir de la base active les 13 400 candidats des campagnes précédentes, ou les archiver chiffrés, avec une durée de conservation définie.
- **Test d'intrusion** avant la prochaine campagne, et revue de code systématique des accès à la base.
- **Journaliser** l'utilisateur authentifié et la taille des réponses, pour pouvoir mesurer une prochaine fuite.
