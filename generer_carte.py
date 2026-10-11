#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Carte des élus : construit carte.html à partir du Répertoire national des élus
(data.gouv.fr), de la géographie des communes (geo.api.gouv.fr) et des députés
de l'Assemblée (pour relier chaque député à sa fiche de votes).

    python3 generer_carte.py [--amo donnees_an/AMO10_...zip] [--sortie carte.html]
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, unicodedata, urllib.request, zipfile

DATASET_RNE = "https://www.data.gouv.fr/api/1/datasets/5c34c4d1634f4173183a64f1/"
GEO_COMMUNES = "https://geo.api.gouv.fr/communes?fields=code,nom,codeDepartement,codeRegion,centre,population&format=json"
UA = {"User-Agent": "carte-elus/1.0"}


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def get(url, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    return data if binary else data.decode("utf-8-sig", errors="replace")


def ressources_rne():
    """Retourne {type: url} à partir du catalogue data.gouv.fr."""
    cat = json.loads(get(DATASET_RNE))
    voulus = {"maires": ("maire",), "deputes": ("depute",), "senateurs": ("senateur",),
              "regionaux": ("regionaux", "regional"), "departementaux": ("departementaux", "departemental"),
              "euro": ("europeen", "europe", "euro")}
    out = {}
    for r in cat.get("resources", []):
        t = norm(r.get("title", "")) + " " + norm(r.get("url", ""))
        if "adjoint" in t or "municipaux" in t or "communautaire" in t or "consulaire" in t or "etranger" in t:
            continue
        for k, mots in voulus.items():
            if k not in out and any(m in t for m in mots):
                if k == "deputes" and "europ" in t:
                    continue
                out[k] = r["url"]
    manquants = [k for k in voulus if k not in out]
    if manquants:
        print(f"  Attention, fichiers RNE introuvables : {manquants}")
    return out


def lire_csv(texte):
    sep = ";" if texte[:2000].count(";") > texte[:2000].count("\t") else "\t"
    rows = list(csv.DictReader(io.StringIO(texte), delimiter=sep))
    return rows


def col(row, *needles):
    """Première colonne dont le nom normalisé contient tous les fragments."""
    for k in row.keys():
        nk = norm(k)
        if all(n in nk for n in needles):
            return row[k]
    return ""


def elu(row):
    return {"nom": (col(row, "nom de l") or col(row, "nom")).strip(),
            "prenom": (col(row, "prenom")).strip(),
            "debut": (col(row, "date de debut du mandat") or col(row, "date de debut"))[:10]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--amo", help="zip AMO10 des députés (pour relier les fiches de votes)")
    p.add_argument("--sortie", default="carte.html")
    p.add_argument("--syntheses", default="syntheses.json")
    args = p.parse_args()

    print("1/4  Catalogue du Répertoire national des élus")
    urls = ressources_rne()
    data = {"genere": dt.datetime.now().strftime("%Y-%m-%d"), "maires": {}, "deputes": {}, "senateurs": {},
            "regionaux": {}, "departementaux": {}, "euro": [], "communes": {}, "regions": {}}

    print("2/4  Téléchargement et lecture des élus")
    if "maires" in urls:
        for r in lire_csv(get(urls["maires"])):
            code = col(r, "code de la commune") or col(r, "code insee")
            if not code:
                continue
            dep = col(r, "code du departement")
            code = code.zfill(5) if not code.startswith(("2A", "2B")) and len(code) < 5 else code
            e = elu(r); e["commune"] = col(r, "libelle de la commune"); e["dep"] = dep
            data["maires"][code] = e
    if "deputes" in urls:
        for r in lire_csv(get(urls["deputes"])):
            dep = col(r, "code du departement"); e = elu(r)
            e["circo"] = col(r, "libelle de la circonscription") or col(r, "code de la circonscription")
            data["deputes"].setdefault(dep, []).append(e)
    if "senateurs" in urls:
        for r in lire_csv(get(urls["senateurs"])):
            data["senateurs"].setdefault(col(r, "code du departement"), []).append(elu(r))
    if "regionaux" in urls:
        for r in lire_csv(get(urls["regionaux"])):
            reg = col(r, "code de la region"); e = elu(r)
            e["section"] = col(r, "libelle de la section")
            data["regionaux"].setdefault(reg, []).append(e)
            data["regions"][reg] = col(r, "libelle de la region")
    if "departementaux" in urls:
        for r in lire_csv(get(urls["departementaux"])):
            dep = col(r, "code du departement"); e = elu(r)
            e["canton"] = col(r, "libelle du canton")
            data["departementaux"].setdefault(dep, []).append(e)
    if "euro" in urls:
        data["euro"] = [elu(r) for r in lire_csv(get(urls["euro"]))]

    print("3/4  Géographie des communes")
    try:
        for c in json.loads(get(GEO_COMMUNES)):
            if (c.get("population") or 0) >= 5000 and c.get("centre"):
                lon, lat = c["centre"]["coordinates"]
                data["communes"][c["code"]] = [round(lat, 4), round(lon, 4), c["nom"], c.get("population", 0)]
    except Exception as e:  # noqa: BLE001
        print(f"  Géographie indisponible : {e}")

    # Lien député RNE -> identifiant officiel PA (fiche de votes)
    if args.amo and os.path.exists(args.amo):
        index = {}
        with zipfile.ZipFile(args.amo) as z:
            for nom in z.namelist():
                if "acteur" in nom and nom.endswith(".json"):
                    a = json.loads(z.read(nom).decode("utf-8-sig")).get("acteur", {})
                    uid = a.get("uid", {}); uid = uid.get("#text") if isinstance(uid, dict) else uid
                    ident = (a.get("etatCivil") or {}).get("ident") or {}
                    index[norm(ident.get("nom", "")) + "|" + norm(ident.get("prenom", "")).split(" ")[0]] = uid
        n = 0
        for lst in data["deputes"].values():
            for e in lst:
                pa = index.get(norm(e["nom"]) + "|" + norm(e["prenom"]).split(" ")[0])
                if pa:
                    e["pa"] = pa; n += 1
        print(f"     Députés reliés à leur fiche de votes : {n}")

    syn = {}
    if os.path.exists(args.syntheses):
        with open(args.syntheses, encoding="utf-8") as f:
            syn = json.load(f)
    data["syntheses"] = {k: v for k, v in syn.items() if not k.startswith("_") or k == "_methode"}

    print("4/4  Génération de la page")
    gabarit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gabarit_carte.html")
    with open(gabarit, encoding="utf-8") as f:
        page = f.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    with open(args.sortie, "w", encoding="utf-8") as f:
        f.write(page.replace("/*__DONNEES__*/null", blob))
    print(f"     {len(data['maires'])} maires, {sum(len(v) for v in data['deputes'].values())} députés, "
          f"{sum(len(v) for v in data['senateurs'].values())} sénateurs, "
          f"{sum(len(v) for v in data['regionaux'].values())} conseillers régionaux, "
          f"{sum(len(v) for v in data['departementaux'].values())} conseillers départementaux, "
          f"{len(data['euro'])} eurodéputés. Fichier : {os.path.abspath(args.sortie)}")


if __name__ == "__main__":
    main()
