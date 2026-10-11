# Suivi nominatif des votes à l'Assemblée nationale

Site généré automatiquement à partir des données ouvertes de l'Assemblée nationale
(XVIIe législature) : tous les scrutins publics, le vote de chaque député, sa participation,
ses votes divergents de son groupe, et des synthèses documentées par député.

## Mise en ligne (une seule fois)

1. Créez un dépôt GitHub (public ou privé), puis déposez-y le contenu de ce dossier,
   y compris le dossier caché `.github`.
2. Dans le dépôt : **Settings → Pages → Build and deployment → Source : GitHub Actions**.
3. Onglet **Actions**, workflow « Générer et publier le suivi des votes », bouton **Run workflow**.

Après deux à trois minutes, l'adresse du site s'affiche dans l'onglet Actions et dans Settings → Pages.
Elle a la forme `https://VOTRE-IDENTIFIANT.github.io/NOM-DU-DEPOT/`.

## Mise à jour

Le site se régénère chaque jour à 7 h (heure de Paris) et à chaque modification du dépôt.
Pour enrichir les fiches, modifiez `syntheses.json` : la publication suit automatiquement.

## Génération locale (facultatif)

```
python3 generer_suivi.py
```

Produit `suivi-votes-deputes.html`, consultable hors ligne.
