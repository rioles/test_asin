#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyse du journal (log) du service d'inscription.
Usage :
    python analyse_journal.py <chemin_du_journal.txt>
"""

import re
import sys
from datetime import datetime, timedelta
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# Fuseau horaire du Bénin = UTC+1 (pas de changement d'heure)
# ---------------------------------------------------------------------------
BENIN_OFFSET = timedelta(hours=1)


def to_benin(ts_utc: datetime) -> datetime:
    return ts_utc + BENIN_OFFSET


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Expressions régulières
# ---------------------------------------------------------------------------
# Ligne d'envoi vers le service d'identification
RE_IDENTITE = re.compile(
    r"^(?P<ts>\S+)\s+\w+\s+\[req:(?P<req>[0-9a-f]+)\]\s+"
    r"appel identite GET /identite/(?P<npi>\d+)\s+->\s+(?P<status>\d+)\s+\((?P<ms>\d+)\s*ms\)"
)

# Ligne d'inscription réussie (POST /api/inscriptions -> 201)
RE_INSCRIPTION = re.compile(
    r"^(?P<ts>\S+)\s+\w+\s+\[req:(?P<req>[0-9a-f]+)\]\s+"
    r"(?P<ip>\S+)\s+POST /api/inscriptions\s+->\s+201\s+\((?P<ms>\d+)\s*ms\)\s+"
    r"concours=(?P<concours>\S+)\s+centre=(?P<centre>\S+)\s+npi=(?P<npi>\d+)\s+"
    r"numero=(?P<numero>\S+)"
)

# Refus d'inscription (409) avec raison
RE_REFUS = re.compile(
    r"^(?P<ts>\S+)\s+\w+\s+\[req:(?P<req>[0-9a-f]+)\]\s+"
    r"(?P<ip>\S+)\s+POST /api/inscriptions\s+->\s+409\s+\((?P<ms>\d+)\s*ms\)\s+"
    r"concours=(?P<concours>\S+)\s+centre=(?P<centre>\S+)\s+npi=(?P<npi>\d+).*?"
    r'erreur="(?P<erreur>[^"]*)"'
)

# Liste des inscrits par centre (requête admin)
RE_LISTE = re.compile(
    r"^(?P<ts>\S+)\s+\w+\s+\[req:(?P<req>[0-9a-f]+)\]\s+"
    r"\S+\s+GET /api/centres/(?P<centre>[A-Z])/inscrits\?concours=(?P<concours>\S+)\s+->\s+200\s+\((?P<ms>\d+)\s*ms\)"
)

# Date de naissance présente dans certains refus âge
RE_NAISSANCE = re.compile(r"naissance=(\d{4}-\d{2}-\d{2})")


def parse_ts(s: str) -> datetime:
    # ex : 2026-11-18T00:00:14.147Z
    return datetime.strptime(s.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f")


# ---------------------------------------------------------------------------
# Étape 1 : lire le fichier et corréler les requêtes par req-id
# ---------------------------------------------------------------------------
def analyser(chemin):
    lignes = []
    with open(chemin, "r", encoding="utf-8", errors="replace") as f:
        lignes = f.readlines()

    # Pour chaque req-id : les lignes d'identification et d'inscription
    identites = {}          # req_id -> dict(ts, npi, status, ms)
    inscriptions = []       # liste de dict
    refus = []              # liste de dict
    listes = []             # liste de dict (durées des listes par centre)

    for ligne in lignes:
        m = RE_IDENTITE.match(ligne)
        if m:
            identites[m.group("req")] = {
                "ts": parse_ts(m.group("ts")),
                "npi": m.group("npi"),
                "status": int(m.group("status")),
                "ms": int(m.group("ms")),
            }
            continue

        m = RE_INSCRIPTION.match(ligne)
        if m:
            inscriptions.append({
                "ts": parse_ts(m.group("ts")),
                "req": m.group("req"),
                "npi": m.group("npi"),
                "numero": m.group("numero"),
                "concours": m.group("concours"),
                "centre": m.group("centre"),
            })
            continue

        m = RE_REFUS.match(ligne)
        if m:
            refus.append({
                "ts": parse_ts(m.group("ts")),
                "req": m.group("req"),
                "npi": m.group("npi"),
                "concours": m.group("concours"),
                "centre": m.group("centre"),
                "erreur": m.group("erreur"),
            })
            continue

        m = RE_LISTE.match(ligne)
        if m:
            listes.append({
                "ts": parse_ts(m.group("ts")),
                "centre": m.group("centre"),
                "concours": m.group("concours"),
                "ms": int(m.group("ms")),
            })
            continue

    return identites, inscriptions, refus, listes


# ---------------------------------------------------------------------------
# Étape 2 : calculs
# ---------------------------------------------------------------------------
def rapports(identites, inscriptions, refus, listes):
    out = []

    # --- 1) Numéros de table attribués plusieurs fois ---------------------
    # Un même numéro (ex C-2861) pour le même concours/centre ne doit sortir
    # qu'une seule fois. On regarde les doublons de "numero".
    nums = Counter(i["numero"] for i in inscriptions)
    doublons_num = {n: c for n, c in nums.items() if c > 1}
    out.append("=" * 70)
    out.append("1) NUMÉROS DE TABLE ATTRIBUÉS PLUSIEURS FOIS")
    out.append("=" * 70)
    if doublons_num:
        for n, c in sorted(doublons_num.items()):
            out.append(f"   {n} : attribué {c} fois")
    else:
        out.append("   Aucun doublon détecté.")

    # --- 2) Inscriptions en double ----------------------------------------
    # Même NPI inscrit plusieurs fois (même concours) = doublon
    cles = Counter((i["npi"], i["concours"]) for i in inscriptions)
    doublons_insc = {k: c for k, c in cles.items() if c > 1}
    out.append("")
    out.append("=" * 70)
    out.append("2) INSCRIPTIONS EN DOUBLE (même NPI + même concours)")
    out.append("=" * 70)
    if doublons_insc:
        for (npi, concours), c in sorted(doublons_insc.items()):
            out.append(f"   NPI {npi} / concours {concours} : {c} inscriptions")
    else:
        out.append("   Aucune inscription en double détectée.")

    # --- 3) Service d'identification >= 5 s ------------------------------
    # On corrèle l'identité et l'inscription qui la suit par le même req-id.
    # On considère la durée totale de la requête d'inscription comme celle
    # "vue" par le service d'identification (le log ne donne pas la durée
    # de la seule sous-requête identité sur la ligne POST).
    # Pour les GET /convocation, la ligne d'identité porte directement la durée.
    out.append("")
    out.append("=" * 70)
    out.append("3) SERVICE D'IDENTIFICATION >= 5 SECONDES (heure du Bénin)")
    out.append("=" * 70)

    evenements = []   # (timestamp_benin, ms, req_id)
    for req_id, info in identites.items():
        if info["ms"] >= 5000:
            evenements.append((to_benin(info["ts"]), info["ms"], req_id))

    if evenements:
        # Regrouper par fenêtres contiguës (écart <= 2 min entre événements)
        evenements.sort()
        groupes = []
        courant = [evenements[0]]
        for ev in evenements[1:]:
            if (ev[0] - courant[-1][0]) <= timedelta(minutes=2):
                courant.append(ev)
            else:
                groupes.append(courant)
                courant = [ev]
        groupes.append(courant)

        for g in groupes:
            debut, fin = g[0][0], g[-1][0]
            reqs = sorted({e[2] for e in g})
            out.append(
                f"   Période : {fmt(debut)} → {fmt(fin)} "
                f"(Bénin) — {len(reqs)} requête(s) lente(s)"
            )
            for e in g:
                out.append(f"        {fmt(e[0])}  req:{e[2]}  {e[1]} ms")
    else:
        out.append("   Aucune requête d'identification >= 5 s.")

    # --- 4) Refus à tort le soir de la clôture du TRÉSOR -----------------
    # Hypothèse : la clôture du Trésor a lieu le 20/11/2026 à 22:59 (Bénin)
    # — les refus "Inscriptions closes pour ce concours." à partir de
    #   cette heure-là sur le concours TRESOR sont considérés comme des
    #   refus à tort (candidats qui avaient encore le droit de s'inscrire
    #   selon la règle métier).
    out.append("")
    out.append("=" * 70)
    out.append("4) REFUS À TORT — SOIR DE LA CLÔTURE DU TRÉSOR")
    out.append("=" * 70)

    # Fenêtre : le 20/11/2026 à partir de 21:00 (Bénin) jusqu'à minuit
    debut_fenetre = datetime(2026, 11, 20, 21, 0, 0)
    fin_fenetre = datetime(2026, 11, 21, 0, 0, 0)

    refus_tresor_cloture = [
        r for r in refus
        if r["concours"] == "TRESOR"
        and "Inscriptions closes" in r["erreur"]
        and debut_fenetre <= to_benin(r["ts"]) < fin_fenetre
    ]
    out.append(f"   Nombre de refus 'Inscriptions closes' sur TRESOR "
               f"entre {fmt(debut_fenetre)} et {fmt(fin_fenetre)} : "
               f"{len(refus_tresor_cloture)}")
    if refus_tresor_cloture:
        par_centre = Counter(r["centre"] for r in refus_tresor_cloture)
        for centre, c in sorted(par_centre.items()):
            out.append(f"        centre {centre} : {c}")

    # --- 5) Candidats refusés à tort pour l'âge -------------------------
    # Le log contient des refus "Âge limite dépassé : 35 ans au 31 décembre
    # de l'année du concours." Certains candidats nés APRES le 31/12/1991
    # ne devraient PAS être refusés (35 ans au 31/12/2026 ⇒ né après le
    # 31/12/1990 ; donc né en 1991 est refusé à tort si l'on compte les
    # 35 ans au 31/12/2026).
    # Règle officielle : 35 ans au 31/12 de l'année du concours (2026) ⇒
    # candidat né après le 31/12/1990 est refusé. Donc tout refus pour un
    # candidat né en 1991 est un refus à tort (il aura 35 ans au plus tard
    # le 31/12/2026).
    out.append("")
    out.append("=" * 70)
    out.append("5) CANDIDATS REFUSÉS À TORT POUR L'ÂGE")
    out.append("=" * 70)
    refus_age = [r for r in refus if "Âge limite dépassé" in r["erreur"]]
    refuses_tort = []
    for r in refus_age:
        # On ne connaît pas la date de naissance sur la ligne de refus 409
        # (seulement npi + message). On la retrouve via la ligne
        # d'identification ? Non : elle n'y est pas. Le log fournit la
        # naissance dans certains refus 409 (format "naissance=YYYY-MM-DD").
        # On la récupère donc en relisant la ligne brute.
        pass

    # On relit les lignes brutes pour extraire naissance des refus âge
    # (méthode robuste, sans dépendre du dict précédent)
    refuses_age_avec_date = []
    for ligne in open(sys.argv[1], encoding="utf-8", errors="replace"):
        m = RE_REFUS.match(ligne)
        if m and "Âge limite dépassé" in m.group("erreur"):
            mn = RE_NAISSANCE.search(ligne)
            if mn:
                refuses_age_avec_date.append({
                    "npi": m.group("npi"),
                    "naissance": mn.group(1),
                    "concours": m.group("concours"),
                })

    for r in refuses_age_avec_date:
        annee_naissance = int(r["naissance"][:4])
        # Refus à tort si le candidat aura 35 ans ou moins au 31/12/2026
        # ⇒ né en 1991 ou après
        if annee_naissance >= 1991:
            refuses_tort.append(r)

    if refuses_tort:
        for r in refuses_tort:
            out.append(
                f"   NPI {r['npi']} — né(e) le {r['naissance']} "
                f"({r['concours']}) : refusé à tort"
            )
        out.append(f"   → Total : {len(refuses_tort)} candidat(s) refusé(s) à tort.")
    else:
        out.append("   Aucun candidat refusé à tort pour l'âge détecté.")

    # --- 6) Durée des listes des inscrits par centre --------------------
    out.append("")
    out.append("=" * 70)
    out.append("6) DURÉE DE LA LISTE DES INSCRITS PAR CENTRE")
    out.append("=" * 70)
    if listes:
        durees = [l["ms"] for l in listes]
        moy = sum(durees) / len(durees)
        maxi = max(durees)
        out.append(f"   Requêtes analysées : {len(listes)}")
        out.append(f"   Durée moyenne : {moy:.0f} ms")
        out.append(f"   Durée maximale : {maxi} ms")
        # détail par centre/concours
        par_cle = defaultdict(list)
        for l in listes:
            par_cle[(l["centre"], l["concours"])].append(l["ms"])
        out.append("   Détail :")
        for (centre, concours), ds in sorted(par_cle.items()):
            out.append(
                f"        centre {centre} / {concours} : "
                f"n={len(ds)}  moy={sum(ds)/len(ds):.0f} ms  max={max(ds)} ms"
            )
    else:
        out.append("   Aucune requête de liste d'inscrits trouvée.")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print("Usage : python analyse_journal.py <chemin_du_journal.txt>")
        sys.exit(1)

    chemin = sys.argv[1]
    try:
        identites, inscriptions, refus, listes = analyser(chemin)
    except FileNotFoundError:
        print(f"Fichier introuvable : {chemin}")
        sys.exit(2)

    print(rapports(identites, inscriptions, refus, listes))


if __name__ == "__main__":
    main()