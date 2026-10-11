#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suivi nominatif des votes de l'Assemblée nationale (XVIIe législature)
=======================================================================

Télécharge les données ouvertes officielles de l'Assemblée nationale
(data.assemblee-nationale.fr), croise l'intégralité des scrutins publics avec
les députés en fonction, puis génère un site autonome (un seul fichier HTML) :

  * hémicycle et liste des députés par groupe (LFI en tête) ;
  * pour chaque député : tous ses votes nominatifs, taux de participation,
    votes divergents de la majorité de son groupe, filtres, export CSV ;
  * pour chaque scrutin : résultat officiel et vote nominatif de chaque député.

Aucune dépendance : Python 3.8+ standard.

Utilisation :
    python3 generer_suivi.py                       # télécharge et génère
    python3 generer_suivi.py --sortie site.html    # nom du fichier produit
    python3 generer_suivi.py --deputes-zip AMO10.zip --scrutins-zip Scrutins.zip
                                                   # fichiers téléchargés à la main

À relancer aussi souvent que souhaité (par exemple chaque matin) : le script
indique le nombre de nouveaux scrutins depuis la dernière génération.
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
import zipfile

LEGISLATURE = 17
URL_DEPUTES = ("https://data.assemblee-nationale.fr/static/openData/repository/"
               f"{LEGISLATURE}/amo/deputes_actifs_mandats_actifs_organes/"
               "AMO10_deputes_actifs_mandats_actifs_organes.json.zip")
URL_SCRUTINS = ("https://data.assemblee-nationale.fr/static/openData/repository/"
                f"{LEGISLATURE}/loi/scrutins/Scrutins.json.zip")
FICHIER_ETAT = ".suivi_votes_etat.json"

# Ordre de l'hémicycle (gauche -> droite) et couleurs, par sigle normalisé
ORDRE_GROUPES = ["GDR", "LFI", "ECOS", "SOC", "LIOT", "DEM", "EPR", "HOR", "DR", "UDR", "RN", "NI"]
COULEURS = {"GDR": "#9e1b1b", "LFI": "#c8213f", "ECOS": "#3f9a4a", "SOC": "#e2577f",
            "LIOT": "#8a77c2", "DEM": "#e07b1f", "EPR": "#e9b818", "HOR": "#3aa6cf",
            "DR": "#1f63c4", "UDR": "#4b3a8f", "RN": "#1b2a5c", "NI": "#9097a1"}
POSITIONS = {"pours": "P", "contres": "C", "abstentions": "A", "nonVotants": "N"}
MAJORITAIRE = {"pour": "P", "contre": "C", "abstention": "A"}


# ----------------------------------------------------------------- utilitaires
def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def txt(x):
    if isinstance(x, dict):
        return x.get("#text") or x.get("$") or ""
    return "" if x is None else str(x)


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def cle_groupe(abrege, libelle):
    a, l = norm(abrege), norm(libelle)
    regles = [("LFI", ["LFI", "INSOUMISE"]), ("ECOS", ["ECOS", "ECOLOGISTE"]),
              ("SOC", ["SOC", "SOCIALISTE"]), ("LIOT", ["LIOT", "LIBERTES"]),
              ("DEM", ["DEM", "DEMOCRATES"]), ("EPR", ["EPR", "ENSEMBLE POUR"]),
              ("HOR", ["HOR", "HORIZONS"]), ("UDR", ["UDR", "UDDPLR", "UNION DES DROITES"]),
              ("DR", ["DR", "DROITE REPUBLICAINE"]), ("RN", ["RN", "RASSEMBLEMENT"]),
              ("GDR", ["GDR", "GAUCHE DEMOCRATE"]), ("NI", ["NI", "NON INSCRIT"])]
    for cle, motifs in regles:
        for m in motifs:
            if a == m or a.startswith(m + "-") or (len(m) > 4 and m in l):
                return cle
    return a or "AUTRE"


def telecharger(url, dossier):
    os.makedirs(dossier, exist_ok=True)
    dest = os.path.join(dossier, url.rsplit("/", 1)[-1])
    print(f"  Téléchargement : {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "suivi-votes/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
            while True:
                bloc = r.read(1 << 20)
                if not bloc:
                    break
                f.write(bloc)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"\nÉchec du téléchargement ({e}).\n"
                 "Téléchargez le fichier depuis https://data.assemblee-nationale.fr "
                 "puis relancez avec --deputes-zip / --scrutins-zip.")
    return dest


def objets_json(chemin_zip):
    with zipfile.ZipFile(chemin_zip) as z:
        for nom in z.namelist():
            if nom.lower().endswith(".json"):
                try:
                    yield json.loads(z.read(nom).decode("utf-8-sig"))
                except ValueError:
                    continue


# ------------------------------------------------------------------- députés
def lire_deputes(chemin_zip):
    acteurs, organes = [], {}
    for obj in objets_json(chemin_zip):
        if "organe" in obj:
            o = obj["organe"]
            organes[txt(o.get("uid"))] = o
        elif "acteur" in obj:
            acteurs.append(obj["acteur"])
        elif "export" in obj:  # variante : un seul fichier global
            exp = obj["export"]
            for o in as_list((exp.get("organes") or {}).get("organe")):
                organes[txt(o.get("uid"))] = o
            acteurs.extend(as_list((exp.get("acteurs") or {}).get("acteur")))

    deputes = []
    for a in acteurs:
        uid = txt(a.get("uid"))
        ident = (a.get("etatCivil") or {}).get("ident") or {}
        actif, gp, circo, debut, qualite = False, None, "", "", ""
        for m in as_list((a.get("mandats") or {}).get("mandat")):
            t, fin = m.get("typeOrgane"), m.get("dateFin")
            if fin:
                continue
            ref = as_list((m.get("organes") or {}).get("organeRef"))
            ref = txt(ref[0]) if ref else ""
            if t == "ASSEMBLEE" and str(m.get("legislature") or LEGISLATURE) == str(LEGISLATURE):
                actif = True
                debut = ((m.get("mandature") or {}).get("datePriseFonction")
                         or m.get("dateDebut") or "")[:10]
                lieu = (m.get("election") or {}).get("lieu") or {}
                dep, num = lieu.get("departement") or "", lieu.get("numCirco") or ""
                circo = f"{dep}, {num}{'re' if str(num) == '1' else 'e'} circonscription" if dep else ""
            elif t == "GP":
                gp = ref
                qualite = ((m.get("infosQualite") or {}).get("libQualite") or "")
        if not actif:
            continue
        deputes.append({"id": uid, "civ": ident.get("civ", ""),
                        "nom": f"{ident.get('prenom', '')} {ident.get('nom', '')}".strip(),
                        "tri": norm(ident.get("nom", "") + " " + ident.get("prenom", "")),
                        "gp": gp, "circo": circo, "debut": debut, "qualite": qualite})

    groupes = {}
    for d in deputes:
        o = organes.get(d["gp"]) or {}
        cle = cle_groupe(o.get("libelleAbrege") or o.get("libelleAbrev") or "", o.get("libelle") or "")
        if not d["gp"]:
            cle = "NI"
        d["g"] = cle
        g = groupes.setdefault(cle, {"k": cle, "n": o.get("libelle") or ("Non inscrits" if cle == "NI" else cle),
                                     "c": COULEURS.get(cle, "#6b7280"), "membres": 0})
        g["membres"] += 1
    return deputes, groupes


# ------------------------------------------------------------------ scrutins
def type_scrutin(titre):
    t = norm(titre)
    if "MOTION" in t:
        return "motion"
    if "L'ENSEMBLE" in t or "L’ENSEMBLE" in t:
        return "ensemble"
    if "AMENDEMENT" in t or "SOUS-AMENDEMENT" in t:
        return "amendement"
    if "ARTICLE" in t:
        return "article"
    if "DECLARATION" in t:
        return "declaration"
    return "autre"


def votants(bloc, cle):
    if not isinstance(bloc, dict):
        return []
    v = bloc.get(cle)
    if not isinstance(v, dict):
        return []
    return [txt(x.get("acteurRef")) for x in as_list(v.get("votant")) if isinstance(x, dict)]


def lire_scrutins(chemin_zip):
    scrutins = []
    for obj in objets_json(chemin_zip):
        lot = []
        if "scrutin" in obj:
            lot = [obj["scrutin"]]
        elif "scrutins" in obj:
            lot = as_list((obj["scrutins"] or {}).get("scrutin"))
        for s in lot:
            try:
                num = int(txt(s.get("numero")))
            except ValueError:
                continue
            synth = (s.get("syntheseVote") or {}).get("decompte") or {}
            titre = txt(s.get("titre")) or txt((s.get("objet") or {}).get("libelle"))
            votes, majorites = {}, {}
            groupes = as_list((((s.get("ventilationVotes") or {}).get("organe") or {})
                               .get("groupes") or {}).get("groupe"))
            for g in groupes:
                vote = g.get("vote") or {}
                maj = MAJORITAIRE.get(norm(txt(vote.get("positionMajoritaire"))).lower(), "")
                nomi = vote.get("decompteNominatif") or {}
                for cle, code in POSITIONS.items():
                    for pa in votants(nomi, cle):
                        votes[pa] = code
                        majorites[pa] = maj
            notes = {}
            mise = s.get("miseAuPoint") or {}
            libelles = {"pours": "voulu voter pour", "contres": "voulu voter contre",
                        "abstentions": "voulu s'abstenir", "nonVotants": "voulu ne pas prendre part au vote",
                        "nonVotantsVolontaires": "voulu ne pas prendre part au vote"}
            for cle, lib in libelles.items():
                for pa in votants(mise, cle):
                    notes[pa] = f"Mise au point : a indiqué avoir {lib}."
            scrutins.append({
                "num": num, "date": txt(s.get("dateScrutin"))[:10], "titre": titre,
                "sort": norm(txt((s.get("sort") or {}).get("code"))).lower(),
                "type": type_scrutin(titre),
                "pour": int(txt(synth.get("pour")) or 0), "contre": int(txt(synth.get("contre")) or 0),
                "abst": int(txt(synth.get("abstentions")) or 0),
                "votes": votes, "maj": majorites, "notes": notes})
    scrutins.sort(key=lambda x: x["num"])
    return scrutins


# ----------------------------------------------------------------- assemblage
def assembler(deputes, groupes, scrutins):
    index = {d["id"]: d for d in deputes}
    for d in deputes:
        d["v"] = bytearray(b"." * len(scrutins))
        d["notes"] = {}
    for i, s in enumerate(scrutins):
        for pa, code in s["votes"].items():
            d = index.get(pa)
            if not d:
                continue
            maj = s["maj"].get(pa, "")
            c = code
            if code in "PCA" and maj and code != maj:
                c = code.lower()  # minuscule = vote différent de la majorité du groupe
            d["v"][i] = ord(c)
        for pa, note in s["notes"].items():
            if pa in index:
                index[pa]["notes"][i] = note

    ordre = {k: i for i, k in enumerate(ORDRE_GROUPES)}
    gl = sorted(groupes.values(), key=lambda g: ordre.get(g["k"], len(ORDRE_GROUPES) - 1))
    return {
        "legislature": LEGISLATURE,
        "genere": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "groupes": gl,
        "scrutins": [[s["num"], s["date"], s["titre"], s["sort"], s["type"], s["pour"], s["contre"], s["abst"]]
                     for s in scrutins],
        "deputes": [{"id": d["id"], "civ": d["civ"], "nom": d["nom"], "tri": d["tri"], "g": d["g"],
                     "circo": d["circo"], "debut": d["debut"], "qualite": d["qualite"],
                     "v": d["v"].decode("ascii"), "notes": d["notes"]}
                    for d in sorted(deputes, key=lambda x: x["tri"])],
    }


def main():
    p = argparse.ArgumentParser(description="Génère le site de suivi nominatif des votes.")
    p.add_argument("--deputes-zip", help="AMO10_deputes_actifs_mandats_actifs_organes.json.zip déjà téléchargé")
    p.add_argument("--scrutins-zip", help="Scrutins.json.zip déjà téléchargé")
    p.add_argument("--cache", default="donnees_an", help="dossier de téléchargement (défaut : donnees_an)")
    p.add_argument("--sortie", default="suivi-votes-deputes.html", help="fichier HTML produit")
    args = p.parse_args()

    print("1/4  Données des députés")
    zd = args.deputes_zip or telecharger(URL_DEPUTES, args.cache)
    print("2/4  Données des scrutins")
    zs = args.scrutins_zip or telecharger(URL_SCRUTINS, args.cache)

    print("3/4  Analyse")
    deputes, groupes = lire_deputes(zd)
    scrutins = lire_scrutins(zs)
    if not deputes or not scrutins:
        sys.exit("Aucune donnée exploitable : vérifiez les fichiers téléchargés.")
    data = assembler(deputes, groupes, scrutins)

    ici = os.path.dirname(os.path.abspath(__file__))
    chemin_syn = os.path.join(ici, "syntheses.json")
    if os.path.exists(chemin_syn):
        with open(chemin_syn, encoding="utf-8") as f:
            syn = json.load(f)
        data["syntheses"] = {k: v for k, v in syn.items() if not k.startswith("_") or k == "_methode"}
        print(f"     Synthèses documentées intégrées : {len([k for k in data['syntheses'] if not k.startswith('_')])}")
    else:
        data["syntheses"] = {}
    gabarit = os.path.join(ici, "gabarit.html")
    with open(gabarit, encoding="utf-8") as f:
        page = f.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = page.replace("/*__DONNEES__*/null", blob)
    with open(args.sortie, "w", encoding="utf-8") as f:
        f.write(page)

    # Suivi : nouveaux scrutins depuis la génération précédente
    dernier = scrutins[-1]["num"]
    precedent = None
    if os.path.exists(FICHIER_ETAT):
        try:
            precedent = json.load(open(FICHIER_ETAT, encoding="utf-8")).get("dernier_scrutin")
        except ValueError:
            pass
    json.dump({"dernier_scrutin": dernier, "date": data["genere"]}, open(FICHIER_ETAT, "w", encoding="utf-8"))

    nb_votes = sum(sum(1 for c in d["v"] if c != ".") for d in data["deputes"])
    print("4/4  Terminé")
    nb = f"{nb_votes:,}".replace(",", " ")
    print(f"     {len(data['deputes'])} députés, {len(scrutins)} scrutins publics "
          f"(du n° {scrutins[0]['num']} au n° {dernier}), {nb} votes nominatifs")
    if precedent is not None:
        print(f"     Nouveaux scrutins depuis la dernière génération : {max(0, dernier - precedent)}")
    print(f"     Fichier : {os.path.abspath(args.sortie)}")


if __name__ == "__main__":
    main()
