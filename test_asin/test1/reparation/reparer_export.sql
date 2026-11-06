-- =============================================================================
-- Réparation de l'export « Inscriptions aux concours » du 21/11/2026 (08 h 00, heure du Bénin)
-- PostgreSQL ≥ 12.  Rejouable sans risque : un second passage ne modifie rien.
--
-- Utilisation :  psql -v ON_ERROR_STOP=1 -d <base> -f reparer_export.sql
--   (le script travaille dans le schéma courant : SET search_path TO <schéma> avant si besoin)
--
-- Ce que fait le script, dans UNE transaction (tout ou rien) :
--   0. garde-fous + verrou des tables (aucune inscription ne peut arriver pendant la réparation)
--   1. heures d'ARRIVÉE des requêtes concernées, tirées du journal (cree_le = heure de FIN)
--   2. inscriptions en double (INC-203)  : on garde la première requête arrivée, on archive l'autre
--   3. numéros de table en double (INC-201) : le premier arrivé garde son numéro, les autres
--      reçoivent un numéro libre ; tout changement est tracé
--   4. Lokossa (INC-202) : AUCUNE suppression. Liste des inscrits au-delà de la capacité,
--      par ordre d'arrivée, avec une colonne « décision » à remplir par la Direction des concours
--   5. contraintes : numéro unique par centre, une inscription par NPI et par concours,
--      pas deux concours le même jour, capacité respectée même avec des requêtes simultanées
--   6. vue des personnes à prévenir
--
-- Règle de départage : « premier arrivé ». L'heure d'arrivée d'une requête = horodatage de la ligne
-- du journal (écrite en fin de traitement) − sa durée. Ex. P-0464 : la requête a93cfec6 est arrivée à
-- 08:21:14.000, avant a061413f (08:21:16.300), même si elle a été enregistrée après.
-- =============================================================================

BEGIN;

SET LOCAL lock_timeout = '10s';

-- -----------------------------------------------------------------------------
-- 0. Garde-fous
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  IF to_regclass(format('%I.django_migrations', current_schema())) IS NOT NULL THEN
    RAISE EXCEPTION 'Le schéma « % » contient les tables de l''application Django : ce script répare l''EXPORT. '
                    'Chargez l''export dans un schéma dédié et faites SET search_path TO ce_schéma.', current_schema();
  END IF;
  IF to_regclass('inscriptions') IS NULL OR to_regclass('centres') IS NULL
     OR to_regclass('concours') IS NULL OR to_regclass('candidats') IS NULL THEN
    RAISE EXCEPTION 'Tables de l''export introuvables dans le schéma « % ».', current_schema();
  END IF;
END $$;

-- Bloque toute écriture concurrente jusqu'au COMMIT (les lectures restent possibles).
LOCK TABLE concours, centres, candidats, inscriptions IN SHARE ROW EXCLUSIVE MODE;

-- -----------------------------------------------------------------------------
-- 1. Heures d'arrivée (journal_production.log)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reparation_arrivees (
  inscription_id INTEGER      PRIMARY KEY,
  req_id         VARCHAR(8)   NOT NULL,
  arrivee_utc    TIMESTAMP(3) NOT NULL
);

INSERT INTO reparation_arrivees (inscription_id, req_id, arrivee_utc) VALUES
  (4749, 'da7305cf', '2026-11-18 15:42:07.318'),
  (4750, 'cd15b304', '2026-11-18 15:42:07.498'),
  (5045, 'aaf0f8db', '2026-11-19 08:11:01.871'),
  (5046, '29c31296', '2026-11-19 08:11:07.847'),
  (5047, 'fd92dc93', '2026-11-19 08:11:11.145'),
  (5048, 'ca41610c', '2026-11-19 08:11:32.514'),
  (5049, '036e0cc8', '2026-11-19 08:11:16.244'),
  (5050, '160e4365', '2026-11-19 08:11:26.471'),
  (5051, 'fd3154d6', '2026-11-19 08:11:42.659'),
  (5052, 'f4cf0482', '2026-11-19 08:11:22.658'),
  (5053, '0af7789b', '2026-11-19 08:11:47.322'),
  (5054, '5239eb06', '2026-11-19 08:11:36.417'),
  (5055, 'baaa5823', '2026-11-19 08:11:51.081'),
  (5056, 'd2920789', '2026-11-19 08:13:14.679'),
  (5057, 'bf13f780', '2026-11-19 08:13:27.089'),
  (5058, '0afbdf2e', '2026-11-19 08:13:35.113'),
  (5060, '14f41bdc', '2026-11-19 08:16:56.481'),
  (5062, '65822124', '2026-11-19 08:17:14.201'),
  (5063, '0b937620', '2026-11-19 08:17:23.617'),
  (5065, 'a061413f', '2026-11-19 08:21:16.300'),
  (5066, 'a93cfec6', '2026-11-19 08:21:14.000'),
  (5067, 'b613990d', '2026-11-19 08:21:29.588'),
  (5068, 'f8d71ec4', '2026-11-19 08:21:25.131'),
  (5070, '26a79251', '2026-11-19 08:21:38.377'),
  (5071, 'e8d7f8fc', '2026-11-19 08:25:02.910'),
  (5072, '88f4d0f6', '2026-11-19 08:25:11.205'),
  (5074, '2002e70f', '2026-11-19 08:29:14.589'),
  (5075, '5a18a15e', '2026-11-19 08:29:08.197'),
  (5076, '63cbaf83', '2026-11-19 08:29:43.936'),
  (5079, '259f9c08', '2026-11-19 08:33:19.999'),
  (5080, 'cf075d17', '2026-11-19 08:33:33.425'),
  (5081, '3dc725d8', '2026-11-19 08:33:32.936')
ON CONFLICT (inscription_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. Inscriptions en double : même NPI, même concours (INC-203)
--    On garde la première requête arrivée ; l'autre est archivée puis supprimée.
--    Jamais dans un centre au-delà de sa capacité (Lokossa) : là, rien n'est supprimé.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reparation_doublons_supprimes (
  id            INTEGER      PRIMARY KEY,   -- id de l'inscription supprimée
  concours_id   INTEGER      NOT NULL,
  centre_id     INTEGER      NOT NULL,
  npi           VARCHAR(10)  NOT NULL,
  numero_table  VARCHAR(6)   NOT NULL,
  statut        VARCHAR(30)  NOT NULL,
  cree_le       TIMESTAMP    NOT NULL,
  conservee_id  INTEGER      NOT NULL,      -- inscription gardée pour ce candidat
  motif         VARCHAR(200) NOT NULL,
  supprimee_le  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);

WITH centres_satures AS (
  SELECT c.id
  FROM centres c
  WHERE (SELECT count(*) FROM inscriptions i WHERE i.centre_id = c.id) > c.capacite
),
classees AS (
  SELECT i.id, i.concours_id, i.centre_id, i.npi, i.numero_table, i.statut, i.cree_le,
         first_value(i.id) OVER w AS conservee_id,
         row_number()      OVER w AS rang
  FROM inscriptions i
  LEFT JOIN reparation_arrivees a ON a.inscription_id = i.id
  WINDOW w AS (PARTITION BY i.npi, i.concours_id
               ORDER BY COALESCE(a.arrivee_utc, i.cree_le), i.id)
)
INSERT INTO reparation_doublons_supprimes
       (id, concours_id, centre_id, npi, numero_table, statut, cree_le, conservee_id, motif)
SELECT id, concours_id, centre_id, npi, numero_table, statut, cree_le, conservee_id,
       'Double inscription au même concours : la première requête arrivée est conservée'
FROM classees
WHERE rang > 1
  AND centre_id NOT IN (SELECT id FROM centres_satures)
ON CONFLICT (id) DO NOTHING;

DELETE FROM inscriptions i
USING reparation_doublons_supprimes d
WHERE i.id = d.id;

-- -----------------------------------------------------------------------------
-- 3. Numéros de table en double dans un centre (INC-201)
--    * Centre dans sa capacité : le premier arrivé garde le numéro ; les suivants, par ordre
--      d'arrivée, reçoivent le plus grand numéro du centre + 1, + 2… (aucun autre candidat
--      ne change de numéro).
--    * Centre au-delà de sa capacité (Lokossa) : les inscriptions en conflit sont renumérotées
--      ensemble, par ordre d'arrivée, sur les numéros en double puis les suivants
--      (L-0297 … L-0307). Ainsi les 300 places réelles (L-0001 … L-0300) vont aux 300 premiers
--      arrivés et les numéros L-0301 et plus désignent les inscrits en attente de décision.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reparation_numeros (
  inscription_id INTEGER      PRIMARY KEY,
  centre_id      INTEGER      NOT NULL,
  npi            VARCHAR(10)  NOT NULL,
  ancien_numero  VARCHAR(6)   NOT NULL,
  nouveau_numero VARCHAR(6)   NOT NULL,
  repare_le      TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);

WITH stats AS (
  SELECT c.id AS centre_id, c.code, c.capacite, count(i.id) AS nb,
         COALESCE(max(CAST(substr(i.numero_table, 3) AS INTEGER)), 0) AS max_num
  FROM centres c
  LEFT JOIN inscriptions i ON i.centre_id = c.id
  GROUP BY c.id, c.code, c.capacite
),
en_double AS (
  SELECT centre_id, numero_table
  FROM inscriptions
  GROUP BY centre_id, numero_table
  HAVING count(*) > 1
),
concernees AS (
  SELECT i.id, i.centre_id, i.npi, i.numero_table,
         CAST(substr(i.numero_table, 3) AS INTEGER) AS num,
         COALESCE(a.arrivee_utc, i.cree_le)          AS arrivee
  FROM inscriptions i
  JOIN en_double d ON d.centre_id = i.centre_id AND d.numero_table = i.numero_table
  LEFT JOIN reparation_arrivees a ON a.inscription_id = i.id
),
-- centres dans leur capacité
normal AS (
  SELECT c.*, row_number() OVER (PARTITION BY c.centre_id, c.numero_table
                                 ORDER BY c.arrivee, c.id) AS rang_groupe
  FROM concernees c JOIN stats s ON s.centre_id = c.centre_id
  WHERE s.nb <= s.capacite
),
normal_cible AS (
  SELECT n.id, n.centre_id, n.npi, n.numero_table,
         s.max_num + row_number() OVER (PARTITION BY n.centre_id ORDER BY n.arrivee, n.id) AS nouveau
  FROM normal n JOIN stats s ON s.centre_id = n.centre_id
  WHERE n.rang_groupe > 1
),
-- centres au-delà de leur capacité
sature AS (
  SELECT c.*, row_number() OVER (PARTITION BY c.centre_id ORDER BY c.arrivee, c.id) AS k
  FROM concernees c JOIN stats s ON s.centre_id = c.centre_id
  WHERE s.nb > s.capacite
),
reserve AS (   -- numéros en double, réutilisés dans l'ordre
  SELECT centre_id, num, row_number() OVER (PARTITION BY centre_id ORDER BY num) AS k,
         count(*) OVER (PARTITION BY centre_id) AS nb_reserve
  FROM (SELECT DISTINCT centre_id, num FROM sature) x
),
sature_cible AS (
  SELECT s.id, s.centre_id, s.npi, s.numero_table,
         COALESCE(r.num,
                  st.max_num + s.k - (SELECT max(r2.nb_reserve) FROM reserve r2
                                      WHERE r2.centre_id = s.centre_id)) AS nouveau
  FROM sature s
  JOIN stats st ON st.centre_id = s.centre_id
  LEFT JOIN reserve r ON r.centre_id = s.centre_id AND r.k = s.k
),
cible AS (
  SELECT * FROM normal_cible
  UNION ALL
  SELECT * FROM sature_cible
)
INSERT INTO reparation_numeros (inscription_id, centre_id, npi, ancien_numero, nouveau_numero)
SELECT c.id, c.centre_id, c.npi, c.numero_table,
       st.code || '-' || lpad(CAST(c.nouveau AS TEXT), 4, '0')
FROM cible c JOIN stats st ON st.centre_id = c.centre_id
WHERE st.code || '-' || lpad(CAST(c.nouveau AS TEXT), 4, '0') <> c.numero_table
ON CONFLICT (inscription_id) DO NOTHING;

UPDATE inscriptions i
SET numero_table = r.nouveau_numero
FROM reparation_numeros r
WHERE r.inscription_id = i.id
  AND i.numero_table = r.ancien_numero;

-- -----------------------------------------------------------------------------
-- 4. Centres au-delà de leur capacité (Lokossa : 307 inscrits pour 300 places)
--    Aucune suppression. Liste, par ordre d'arrivée, des inscrits au-delà de la capacité.
--    Décision à prendre par la Direction des concours, à saisir dans la colonne « decision ».
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decision_capacite (
  inscription_id   INTEGER      PRIMARY KEY,
  centre_id        INTEGER      NOT NULL,
  rang_arrivee     INTEGER      NOT NULL,      -- rang dans le centre, 1 = premier arrivé
  capacite         INTEGER      NOT NULL,
  npi              VARCHAR(10)  NOT NULL,
  concours_id      INTEGER      NOT NULL,
  numero_table     VARCHAR(6)   NOT NULL,
  arrivee_utc      TIMESTAMP(3) NOT NULL,
  req_id           VARCHAR(8),
  decision         VARCHAR(30)
    CHECK (decision IN ('AUGMENTER_CAPACITE', 'TRANSFERER_AUTRE_CENTRE', 'ANNULER')),
  centre_transfert VARCHAR(1),
  decide_par       VARCHAR(100),
  decide_le        TIMESTAMP,
  CHECK ((decision IS NULL) = (decide_par IS NULL)),
  CHECK (decision IS DISTINCT FROM 'TRANSFERER_AUTRE_CENTRE' OR centre_transfert IS NOT NULL)
);

WITH rangs AS (
  SELECT i.id, i.centre_id, c.capacite, i.npi, i.concours_id, i.numero_table,
         COALESCE(a.arrivee_utc, i.cree_le) AS arrivee, a.req_id,
         row_number() OVER (PARTITION BY i.centre_id
                            ORDER BY COALESCE(a.arrivee_utc, i.cree_le), i.id) AS rang,
         count(*)     OVER (PARTITION BY i.centre_id) AS nb
  FROM inscriptions i
  JOIN centres c ON c.id = i.centre_id
  LEFT JOIN reparation_arrivees a ON a.inscription_id = i.id
)
INSERT INTO decision_capacite
       (inscription_id, centre_id, rang_arrivee, capacite, npi, concours_id, numero_table, arrivee_utc, req_id)
SELECT id, centre_id, rang, capacite, npi, concours_id, numero_table, arrivee, req_id
FROM rangs
WHERE nb > capacite AND rang > capacite
ON CONFLICT (inscription_id) DO NOTHING;

CREATE OR REPLACE VIEW decision_capacite_a_valider AS
SELECT ce.nom AS centre, d.rang_arrivee, d.capacite, d.numero_table, co.code AS concours,
       d.npi, ca.nom, ca.prenoms, d.arrivee_utc, d.req_id,
       d.decision, d.centre_transfert, d.decide_par, d.decide_le
FROM decision_capacite d
JOIN centres  ce ON ce.id = d.centre_id
JOIN concours co ON co.id = d.concours_id
LEFT JOIN candidats ca ON ca.npi = d.npi;

-- -----------------------------------------------------------------------------
-- 5. Contraintes : ces incidents ne peuvent plus se reproduire
-- -----------------------------------------------------------------------------
-- INC-201 : un numéro de table n'existe qu'une fois dans un centre (tous concours confondus)
CREATE UNIQUE INDEX IF NOT EXISTS uq_inscriptions_centre_numero ON inscriptions (centre_id, numero_table);

-- INC-203 : une seule inscription par NPI et par concours
CREATE UNIQUE INDEX IF NOT EXISTS uq_inscriptions_npi_concours  ON inscriptions (npi, concours_id);

-- Règle « pas deux concours le même jour », que la même concurrence pouvait contourner :
-- date de l'épreuve recopiée dans inscriptions, garantie identique à celle du concours (clé étrangère).
ALTER TABLE inscriptions ADD COLUMN IF NOT EXISTS date_epreuve DATE;
UPDATE inscriptions i SET date_epreuve = c.date_epreuve
FROM concours c
WHERE c.id = i.concours_id AND i.date_epreuve IS DISTINCT FROM c.date_epreuve;
ALTER TABLE inscriptions ALTER COLUMN date_epreuve SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_concours_id_date ON concours (id, date_epreuve);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'fk_inscriptions_concours_date'
                   AND conrelid = 'inscriptions'::regclass) THEN
    ALTER TABLE inscriptions ADD CONSTRAINT fk_inscriptions_concours_date
      FOREIGN KEY (concours_id, date_epreuve) REFERENCES concours (id, date_epreuve) ON UPDATE CASCADE;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_inscriptions_npi_jour ON inscriptions (npi, date_epreuve);

-- Un NPI = un candidat ; et INC-207 : accès indexé aux inscrits d'un centre
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidats_npi ON candidats (npi);
CREATE INDEX IF NOT EXISTS ix_inscriptions_centre_concours ON inscriptions (centre_id, concours_id, numero_table);

-- INC-202 : capacité. Compteur d'inscrits par centre, tenu par la base elle-même.
-- L'incrément conditionnel « inscrits < capacite » verrouille la ligne du centre : deux
-- inscriptions simultanées ne peuvent plus prendre la même dernière place.
ALTER TABLE centres ADD COLUMN IF NOT EXISTS inscrits INTEGER NOT NULL DEFAULT 0;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'ck_centres_inscrits_positif' AND conrelid = 'centres'::regclass) THEN
    ALTER TABLE centres ADD CONSTRAINT ck_centres_inscrits_positif CHECK (inscrits >= 0);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION inscriptions_controle_ecriture() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- L'application n'a pas à fournir date_epreuve : elle vient toujours du concours.
  SELECT c.date_epreuve INTO NEW.date_epreuve FROM concours c WHERE c.id = NEW.concours_id;

  IF TG_OP = 'INSERT' OR NEW.centre_id IS DISTINCT FROM OLD.centre_id THEN
    UPDATE centres SET inscrits = inscrits + 1
    WHERE id = NEW.centre_id AND inscrits < capacite;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Le centre d''examen % est complet.', NEW.centre_id
        USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
      UPDATE centres SET inscrits = inscrits - 1 WHERE id = OLD.centre_id;
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION inscriptions_apres_suppression() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE centres SET inscrits = inscrits - 1 WHERE id = OLD.centre_id;
  RETURN OLD;
END $$;

DROP TRIGGER IF EXISTS trg_inscriptions_controle ON inscriptions;
CREATE TRIGGER trg_inscriptions_controle
  BEFORE INSERT OR UPDATE OF concours_id, centre_id ON inscriptions
  FOR EACH ROW EXECUTE FUNCTION inscriptions_controle_ecriture();

DROP TRIGGER IF EXISTS trg_inscriptions_suppression ON inscriptions;
CREATE TRIGGER trg_inscriptions_suppression
  AFTER DELETE ON inscriptions
  FOR EACH ROW EXECUTE FUNCTION inscriptions_apres_suppression();

-- (Re)calcul exact du compteur. Lokossa reste à 307 : la base refusera tout nouvel inscrit
-- tant que la décision n'a pas ramené le centre sous sa capacité (ou augmenté celle-ci).
UPDATE centres c SET inscrits = x.nb
FROM (SELECT ce.id, count(i.id) AS nb
      FROM centres ce LEFT JOIN inscriptions i ON i.centre_id = ce.id
      GROUP BY ce.id) x
WHERE x.id = c.id AND c.inscrits IS DISTINCT FROM x.nb;

-- -----------------------------------------------------------------------------
-- 6. Personnes à prévenir (candidats concernés par la réparation)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW reparation_a_prevenir AS
SELECT 'NOUVEAU_NUMERO'::TEXT AS motif, ce.nom AS centre, ca.npi, ca.nom, ca.prenoms,
       r.ancien_numero, r.nouveau_numero,
       'Nouvelle convocation : votre numéro de table devient ' || r.nouveau_numero AS message
FROM reparation_numeros r
JOIN centres ce ON ce.id = r.centre_id
LEFT JOIN candidats ca ON ca.npi = r.npi
WHERE r.inscription_id NOT IN (SELECT inscription_id FROM decision_capacite)
UNION ALL
SELECT 'CONVOCATION_EN_DOUBLE_ANNULEE', ce.nom, ca.npi, ca.nom, ca.prenoms,
       d.numero_table, i.numero_table,
       'Une seule inscription est conservée ; seule la convocation n° ' || i.numero_table || ' est valable'
FROM reparation_doublons_supprimes d
JOIN inscriptions i ON i.id = d.conservee_id
JOIN centres ce ON ce.id = i.centre_id
LEFT JOIN candidats ca ON ca.npi = d.npi
UNION ALL
SELECT 'CAPACITE_DEPASSEE_DECISION_EN_ATTENTE', ce.nom, ca.npi, ca.nom, ca.prenoms,
       r.ancien_numero, d.numero_table,
       'Inscription au-delà de la capacité du centre : décision de la Direction des concours en attente'
FROM decision_capacite d
JOIN centres ce ON ce.id = d.centre_id
LEFT JOIN candidats ca ON ca.npi = d.npi
LEFT JOIN reparation_numeros r ON r.inscription_id = d.inscription_id
WHERE d.decision IS NULL;

-- -----------------------------------------------------------------------------
-- Bilan
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  n_suppr INTEGER; n_renum INTEGER; n_decision INTEGER; n_dup_num INTEGER; n_dup_insc INTEGER;
BEGIN
  SELECT count(*) INTO n_suppr    FROM reparation_doublons_supprimes;
  SELECT count(*) INTO n_renum    FROM reparation_numeros;
  SELECT count(*) INTO n_decision FROM decision_capacite WHERE decision IS NULL;
  SELECT count(*) INTO n_dup_num  FROM (SELECT 1 FROM inscriptions GROUP BY centre_id, numero_table HAVING count(*) > 1) x;
  SELECT count(*) INTO n_dup_insc FROM (SELECT 1 FROM inscriptions GROUP BY npi, concours_id HAVING count(*) > 1) x;
  RAISE NOTICE 'Doublons archivés et supprimés : %', n_suppr;
  RAISE NOTICE 'Numéros de table réattribués : %', n_renum;
  RAISE NOTICE 'Inscriptions au-delà de la capacité, décision en attente : %', n_decision;
  RAISE NOTICE 'Numéros encore en double : %, inscriptions encore en double : %', n_dup_num, n_dup_insc;
END $$;

COMMIT;
