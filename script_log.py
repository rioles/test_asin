#!/usr/bin/env python3
"""
Analyse du journal du service d'inscription aux concours.

Usage :
    python script_log.py <chemin_du_journal>

Établit, en heure du Bénin (UTC+1) :
  1. les numéros de table attribués plusieurs fois ;
  2. les inscriptions en double ;
  3. la période où le service d'identification a mis 5 s ou plus, et les requêtes touchées ;
  4. les refus à tort le soir de la clôture du Trésor ;
  5. les candidats refusés à tort pour l'âge ;
  6. la durée moyenne et maximale de la liste des inscrits, par centre.

Rappels sur le format du journal :
  * chaque ligne est horodatée en UTC ;
  * la ligne d'une requête est écrite à la FIN de son traitement, avec sa durée :
    heure d'arrivée = horodatage - durée ;
  * l'appel au service d'identification a sa propre ligne, avec le même identifiant de requête.
"""
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

BENIN = timezone(timedelta(hours=1), "Bénin")   # UTC+1, sans heure d'été
SEUIL_LENT_MS = 5000
AGE_MAX = 35

# Données du dossier technique (le journal ne contient ni les dates d'épreuve ni les clôtures).
ANNEE_CONCOURS = {"DOUANES": 2026, "IMPOTS": 2026, "TRESOR": 2026}
CLOTURE_TRESOR = datetime(2026, 11, 20, 23, 59, tzinfo=BENIN)   # « fixée à 23 h 59 », heure du Bénin

RE_LIGNE = re.compile(r"^(?P<ts>\S+)\s+(?P<niveau>[A-Z]+)\s+\[req:(?P<req>\w+)\]\s+(?P<reste>.*)$")
RE_IDENTITE = re.compile(r"^appel identite GET (?P<url>\S+) -> (?P<code>\d+) \((?P<ms>\d+) ms\)")
RE_REQUETE = re.compile(
    r"^(?P<ip>\S+) (?P<methode>[A-Z]+) (?P<chemin>\S+) -> (?P<code>\d+) \((?P<ms>\d+) ms\)(?P<extra>.*)$")
RE_CHAMP = re.compile(r'(\w+)=("[^"]*"|\S+)')


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
@dataclass
class Evenement:
    req: str
    fin: datetime            # heure du Bénin
    ms: int
    code: int
    ip: str = ""
    methode: str = ""
    chemin: str = ""
    champs: dict = field(default_factory=dict)

    @property
    def debut(self) -> datetime:
        return self.fin - timedelta(milliseconds=self.ms)


@dataclass
class Journal:
    requetes: list            # Evenement des lignes de requête
    identites: list           # Evenement des appels au service d'identification
    lignes_ignorees: int


def lire_horodatage(texte: str) -> datetime:
    return datetime.fromisoformat(texte.replace("Z", "+00:00")).astimezone(BENIN)


def lire_journal(chemin: str) -> Journal:
    requetes, identites, ignorees = [], [], 0
    with open(chemin, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            m = RE_LIGNE.match(ligne.rstrip("\n"))
            if not m:
                ignorees += ligne.strip() != ""
                continue
            fin, req, reste = lire_horodatage(m["ts"]), m["req"], m["reste"]
            mi = RE_IDENTITE.match(reste)
            if mi:
                identites.append(Evenement(req, fin, int(mi["ms"]), int(mi["code"]), chemin=mi["url"]))
                continue
            mr = RE_REQUETE.match(reste)
            if mr:
                champs = {k: v.strip('"') for k, v in RE_CHAMP.findall(mr["extra"])}
                requetes.append(Evenement(req, fin, int(mr["ms"]), int(mr["code"]), mr["ip"],
                                          mr["methode"], mr["chemin"], champs))
            else:
                ignorees += 1
    return Journal(requetes, identites, ignorees)


def inscriptions_reussies(j: Journal):
    return [e for e in j.requetes
            if e.methode == "POST" and e.chemin.startswith("/api/inscriptions") and e.code == 201]


def refus(j: Journal, motif: str):
    return [e for e in j.requetes
            if e.methode == "POST" and e.chemin.startswith("/api/inscriptions")
            and e.code >= 400 and motif in e.champs.get("erreur", "")]


# ---------------------------------------------------------------------------
# 1. Numéros de table attribués plusieurs fois
# ---------------------------------------------------------------------------
def numeros_en_double(j: Journal) -> dict:
    """{numéro: [inscriptions]} — le numéro (« P-0464 ») contient déjà le centre :
    l'unicité s'entend dans le centre, tous concours confondus."""
    par_numero = defaultdict(list)
    for e in inscriptions_reussies(j):
        par_numero[e.champs["numero"]].append(e)
    return {n: sorted(es, key=lambda e: e.fin) for n, es in sorted(par_numero.items()) if len(es) > 1}


# ---------------------------------------------------------------------------
# 2. Inscriptions en double
# ---------------------------------------------------------------------------
def inscriptions_en_double(j: Journal) -> dict:
    """{(npi, concours): [inscriptions, par ordre d'arrivée]}"""
    par_cle = defaultdict(list)
    for e in inscriptions_reussies(j):
        par_cle[(e.champs["npi"], e.champs["concours"])].append(e)
    return {k: sorted(es, key=lambda e: e.debut) for k, es in sorted(par_cle.items()) if len(es) > 1}


# ---------------------------------------------------------------------------
# 3. Lenteur du service d'identification
# ---------------------------------------------------------------------------
@dataclass
class Periode:
    debut: datetime
    fin: datetime
    appels: list               # appels au service ≥ 5 s
    requetes: list             # requêtes touchées (même identifiant que l'appel lent)


def periodes_lentes(j: Journal, seuil_ms: int = SEUIL_LENT_MS) -> list:
    """Une période commence avec le premier appel lent (≥ 5 s) et se termine au premier appel
    redevenu rapide. Les moments sans aucun appel ne coupent pas la période : on ne sait
    pas que le service allait mieux tant qu'aucun appel rapide ne le montre.
    Bornes : arrivée du premier appel lent → fin du dernier."""
    groupes, en_cours = [], None
    for a in sorted(j.identites, key=lambda a: a.debut):
        if a.ms >= seuil_ms:
            if en_cours is None:
                en_cours = [a.debut, a.fin, []]
                groupes.append(en_cours)
            en_cours[1] = max(en_cours[1], a.fin)
            en_cours[2].append(a)
        else:
            en_cours = None
    par_req = {e.req: e for e in j.requetes}
    return [Periode(d, f, appels, [par_req[a.req] for a in appels if a.req in par_req])
            for d, f, appels in groupes]


def route(e: Evenement) -> str:
    return re.sub(r"/\d+", "/{id}", e.chemin.split("?")[0])


# ---------------------------------------------------------------------------
# 4. Refus à tort, soir de la clôture du Trésor
# ---------------------------------------------------------------------------
@dataclass
class RefusCloture:
    a_tort: list                  # refus « Inscriptions closes » arrivés avant la clôture réelle
    legitimes: list               # refus après la clôture réelle
    premier_refus: datetime | None
    candidats: set                # NPI refusés à tort
    jamais_inscrits: set          # … sans inscription au Trésor dans le journal


def refus_cloture_tresor(j: Journal, cloture: datetime = CLOTURE_TRESOR) -> RefusCloture:
    closes = sorted((e for e in refus(j, "Inscriptions closes") if e.champs.get("concours") == "TRESOR"),
                    key=lambda e: e.debut)
    a_tort = [e for e in closes if e.debut <= cloture]
    inscrits = {e.champs["npi"] for e in inscriptions_reussies(j) if e.champs.get("concours") == "TRESOR"}
    candidats = {e.champs["npi"] for e in a_tort}
    return RefusCloture(a_tort, [e for e in closes if e.debut > cloture],
                        closes[0].fin if closes else None, candidats, candidats - inscrits)


# ---------------------------------------------------------------------------
# 5. Candidats refusés à tort pour l'âge
# ---------------------------------------------------------------------------
def age_au_31_decembre(naissance: date, annee: int) -> int:
    """Âge révolu au 31 décembre : l'anniversaire de l'année est toujours passé."""
    return annee - naissance.year


def age_ancienne_formule(naissance: date, annee: int) -> float:
    """Formule du dossier technique (fautive) : jours jusqu'au 31/12 divisés par 365."""
    return (date(annee, 12, 31) - naissance).days / 365


def refus_age_a_tort(j: Journal) -> list:
    """[(refus, naissance, âge révolu, âge selon l'ancienne formule)] — un candidat par
    (NPI, concours), au premier refus ; seuls les refus contraires à la règle des 35 ans."""
    vus, res = set(), []
    for e in sorted(refus(j, "ge limite"), key=lambda e: e.fin):
        cle = (e.champs.get("npi"), e.champs.get("concours"))
        if "naissance" not in e.champs or cle in vus:
            continue
        naissance = date.fromisoformat(e.champs["naissance"])
        annee = ANNEE_CONCOURS.get(e.champs.get("concours"), e.fin.year)
        age = age_au_31_decembre(naissance, annee)
        if age <= AGE_MAX:
            vus.add(cle)
            res.append((e, naissance, age, age_ancienne_formule(naissance, annee)))
    return res


# ---------------------------------------------------------------------------
# 6. Durée de la liste des inscrits par centre
# ---------------------------------------------------------------------------
RE_LISTE = re.compile(r"^/api/centres/(?P<centre>[^/]+)/inscrits")


def durees_listes(j: Journal) -> dict:
    """{centre: [durées en ms]}"""
    par_centre = defaultdict(list)
    for e in j.requetes:
        m = RE_LISTE.match(e.chemin)
        if e.methode == "GET" and m and e.code == 200:
            par_centre[m["centre"]].append(e.ms)
    return dict(sorted(par_centre.items()))


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
def h(dt: datetime, ms: bool = False) -> str:
    return dt.strftime("%d/%m %H:%M:%S.%f")[:-3] if ms else dt.strftime("%d/%m %H:%M:%S")


def titre(texte: str) -> str:
    return f"\n{'=' * 78}\n{texte}\n{'=' * 78}"


def rapport(j: Journal) -> str:
    out = [f"Toutes les heures sont en heure du Bénin (UTC+1). "
           f"{len(j.requetes)} requêtes, {len(j.identites)} appels au service d'identification."]

    # 1
    doubles = numeros_en_double(j)
    partages = {n: es for n, es in doubles.items() if len({e.champs['npi'] for e in es}) > 1}
    out.append(titre(f"1) NUMÉROS DE TABLE ATTRIBUÉS PLUSIEURS FOIS : {len(doubles)} numéros, "
                     f"{sum(map(len, doubles.values()))} attributions"))
    out.append(f"   dont {len(partages)} partagés par des candidats différents ; "
               f"{len(doubles) - len(partages)} dus à une double inscription du même candidat")
    for n, es in doubles.items():
        nature = "candidats différents" if n in partages else "même candidat"
        out.append(f"   {n} : {len(es)} fois ({nature})")
        for e in es:
            out.append(f"      {h(e.fin)}  NPI {e.champs['npi']}  {e.champs['concours']:<8} req:{e.req}")

    # 2
    insc = inscriptions_en_double(j)
    out.append(titre(f"2) INSCRIPTIONS EN DOUBLE (même NPI, même concours) : {len(insc)}"))
    for (npi, concours), es in insc.items():
        ecart = (es[1].debut - es[0].debut).total_seconds()
        out.append(f"   NPI {npi} {concours:<8} centre {es[0].champs['centre']}  "
                   f"{len(es)} inscriptions, 2e envoi {ecart:.1f} s après le 1er")
        for e in es:
            out.append(f"      arrivée {h(e.debut, True)}  fin {h(e.fin)}  ({e.ms} ms)  "
                       f"IP {e.ip}  {e.champs['numero']}  req:{e.req}")

    # 3
    periodes = periodes_lentes(j)
    out.append(titre("3) SERVICE D'IDENTIFICATION À 5 SECONDES OU PLUS"))
    if not periodes:
        out.append("   Aucun appel de 5 s ou plus.")
    for p in periodes:
        ms = sorted(a.ms for a in p.appels)
        out.append(f"   Période : {h(p.debut)} → {h(p.fin)}  "
                   f"(durée {(p.fin - p.debut).total_seconds() / 60:.0f} min)")
        out.append(f"   Requêtes touchées : {len(p.requetes)}  "
                   f"(appels au service : médiane {ms[len(ms) // 2] / 1000:.1f} s, "
                   f"maximum {ms[-1] / 1000:.1f} s)")
        par_route = defaultdict(list)
        for e in p.requetes:
            par_route[f"{e.methode} {route(e)}"].append(e.ms)
        for r, ds in sorted(par_route.items()):
            out.append(f"      {r:<42} {len(ds):>3} requêtes, moyenne {sum(ds) / len(ds) / 1000:.1f} s, "
                       f"maximum {max(ds) / 1000:.1f} s")

    # 4
    rc = refus_cloture_tresor(j)
    out.append(titre(f"4) REFUS À TORT, SOIR DE LA CLÔTURE DU TRÉSOR (clôture réelle : {h(CLOTURE_TRESOR)})"))
    if rc.premier_refus:
        out.append(f"   Premier refus « Inscriptions closes » : {h(rc.premier_refus)}")
    out.append(f"   Refus à tort (avant la clôture réelle) : {len(rc.a_tort)} refus, "
               f"{len(rc.candidats)} candidats")
    out.append(f"   dont candidats sans aucune inscription au Trésor dans le journal : {len(rc.jamais_inscrits)}")
    out.append(f"   Refus légitimes (après la clôture) : {len(rc.legitimes)}")
    par_centre = defaultdict(int)
    for e in rc.a_tort:
        par_centre[e.champs.get("centre", "?")] += 1
    out.append("   Refus à tort par centre : " + ", ".join(f"{c} {n}" for c, n in sorted(par_centre.items())))

    # 5
    age = refus_age_a_tort(j)
    out.append(titre(f"5) CANDIDATS REFUSÉS À TORT POUR L'ÂGE : {len(age)} "
                     f"(sur {len(refus(j, 'ge limite'))} refus pour l'âge)"))
    for e, naissance, a, ancien in age:
        out.append(f"   {h(e.fin)}  NPI {e.champs['npi']}  né(e) le {naissance:%d/%m/%Y}  "
                   f"{a} ans au 31/12 (ancienne formule : {ancien:.2f})  "
                   f"{e.champs['concours']:<8} centre {e.champs.get('centre', '?')}")

    # 6
    out.append(titre("6) DURÉE DE LA LISTE DES INSCRITS, PAR CENTRE"))
    out.append(f"   {'Centre':<8}{'Appels':>8}{'Moyenne':>12}{'Maximum':>12}")
    for centre, ds in durees_listes(j).items():
        out.append(f"   {centre:<8}{len(ds):>8}{sum(ds) / len(ds) / 1000:>11.1f}s{max(ds) / 1000:>11.1f}s")

    if j.lignes_ignorees:
        out.append(f"\n(Lignes non reconnues : {j.lignes_ignorees})")
    return "\n".join(out)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # La console Windows est en cp1252 : sans cela, « → » ou « É » font planter l'affichage.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 1:
        print("Usage : python script_log.py <chemin_du_journal>", file=sys.stderr)
        return 1
    try:
        journal = lire_journal(argv[0])
    except FileNotFoundError:
        print(f"Fichier introuvable : {argv[0]}", file=sys.stderr)
        return 2
    print(rapport(journal))
    return 0


if __name__ == "__main__":
    sys.exit(main())
