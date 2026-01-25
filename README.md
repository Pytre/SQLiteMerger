# SQLite Merger

Application Python pour fusionner et traiter des données dans une base SQLite.

## Description

SQLite Merger est une application de consolidation de données qui permet de :
- **Convertir** des tables Excel en fichiers CSV temporaires
- **Importer** des fichiers CSV (existants ou depuis des dossiers) dans une base SQLite
- **Traiter** les données via des commandes SQL configurables
- **Exporter** des résultats vers des fichiers CSV
- **Gérer** l'interruption utilisateur et la progression en temps réel

## Architecture

### Structure des fichiers

```
SQLite_Merger/
├── app.py                              # Interface graphique (ttkbootstrap)
├── about.py                            # Métadonnées de l'application
├── about_window.py                     # Fenêtre "À propos"
├── merger.py                           # Orchestration principale
├── config.py                           # Chargement/sauvegarde configuration
├── models.py                           # Modèles de données (Table, Variable, Command)
├── sqlite_processor.py                 # Opérations SQLite (import/export)
├── excel_converter.py                  # Conversion Excel → CSV
├── calculator.py                       # Évaluation des expressions par défaut
├── constants.py                        # Constantes (encodages, logger)
├── utils.py                            # Fonctions utilitaires
├── res/                                # Ressources (icônes, licence)
├── SQLite_Merger.cfg                   # Configuration JSON
├── SQLite_Merger_DB_Template.sqlite    # Template de base de données
└── SQLite_Merger_Tables_Infos.xlsx     # Tables Excel de configuration
```

### Modules principaux

| Module | Rôle |
|--------|------|
| `app.py` | Interface graphique avec ttkbootstrap |
| `merger.py` | Classe `SQLiteMerger` - orchestration du traitement |
| `config.py` | `ConfigLoader`, `RunConfig`, `ProcessContext` |
| `models.py` | `Table`, `Variable`, `Command` et leurs configs |
| `sqlite_processor.py` | `SQLiteProcessor` - import/export SQLite |
| `excel_converter.py` | `ExcelConverter` - conversion Excel → CSV |

### Classes de configuration

- **`RunConfig`** : Configuration d'exécution (chemins, tables, variables, commandes)
- **`ProcessContext`** : Contexte de traitement (timestamp, dossier temporaire, base SQLite)
- **`Table`** : Définition d'une table (source CSV, table SQL cible, encodage)
- **`Variable`** : Variable configurable avec validation regex et niveaux d'accès
- **`Command`** : Commande SQL à exécuter (phases init/post_imports)

## Prérequis

- **Python 3.10+** (utilise les type hints modernes)
- **Modules Python** :
  - `openpyxl` - Lecture de fichiers Excel
  - `ttkbootstrap` - Interface graphique moderne
  - `Pillow` - Traitement d'images (optionnel, pour l'icône)

## Installation

### 1. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 2. Configuration

Créer/modifier le fichier `SQLite_Merger.cfg` (format JSON). Voir [config_help.md](config_help.md) pour la documentation complète.

### 3. Fichiers requis

- `SQLite_Merger.cfg` - Configuration JSON
- `SQLite_Merger_DB_Template.sqlite` - Template de base de données
- `SQLite_Merger_Tables_Infos.xlsx` - Tables Excel (optionnel, selon config)

## Utilisation

### Mode graphique (recommandé)

```bash
python app.py
```

Options en ligne de commande :
```bash
python app.py --config <fichier.cfg> --template <template.sqlite> --infos <tables.xlsx>
```

### Mode ligne de commande

```bash
python merger.py
```

Le script demande interactivement les informations nécessaires.

## Flux de traitement

1. **Chargement configuration** depuis `SQLite_Merger.cfg`
2. **Création dossier temporaire** avec timestamp
3. **Copie template SQLite** dans le dossier temporaire
4. **Conversion Excel → CSV** pour les tables avec `excel_name`
5. **Identification sources CSV** pour les tables avec `csv_source` (fichiers ou dossiers)
6. **Import des données** dans SQLite (dimensions puis faits)
7. **Exécution commandes SQL** (init puis post_imports)
8. **Export des résultats** vers CSV
9. **Récupération fichiers** dans le dossier de sortie
10. **Nettoyage** du dossier temporaire

## Fonctionnalités

### Types de sources CSV

| Type | Attribut config | Description |
|------|-----------------|-------------|
| Excel | `excel_name` + `csv_name` | Converti depuis une table Excel |
| Fichier existant | `csv_source` (fichier) | Fichier CSV existant |
| Dossier multi-fichiers | `csv_source` (dossier) + `csv_pattern_regex` | Tous les fichiers matchant le pattern |

### Encodage des fichiers

| Source | Encodage par défaut | Configurable via |
|--------|---------------------|------------------|
| Excel (auto-généré) | `cp1252` | `csv_encoding` (table) |
| CSV source existant | `utf-8-sig` | `input_codec` (global) ou `csv_encoding` (table) |
| Export OUTPUT | `cp1252` | `output_codec` (global) ou `csv_encoding` (table) |

### Variables configurables

Les variables peuvent :
- Avoir des valeurs par défaut calculées (expressions avec `=`)
- Être validées par regex (`regex_ctrl`)
- Être injectées dans la base SQLite (`sql_table`, `sql_set_col`, `sql_where_col`)
- Être utilisées comme placeholders dans les chemins (`{variable}`)
- Avoir différents niveaux d'accès : `user`, `advanced`, `internal`

### Chemins dynamiques

Les chemins `csv_source`, `csv_name` et `kept_db_name` supportent les variables :
```
C:/Data/{periode}/balance.csv
Export_{periode}_{timestamp}.csv
```

### Options de configuration

| Option | Description |
|--------|-------------|
| `copy_csv_to_temp` | Copie les CSV sources dans le dossier temporaire |
| `csv_missing_ok` | Ne pas alerter si une source CSV est introuvable |
| `keep_db` | Conserver la base SQLite après traitement |
| `disable_output` | Désactiver l'export des fichiers CSV |

### Gestion de l'interruption

- Bouton "Arrêter" dans l'interface graphique
- Ctrl+C en mode CLI
- Points de contrôle durant le traitement

### Optimisations SQLite

- `PRAGMA synchronous = OFF`
- `PRAGMA journal_mode = MEMORY`
- `PRAGMA temp_store = MEMORY`
- Cache de 64 MB
- Fonction `REGEXP` personnalisée

## Fichiers générés

Les fichiers de sortie sont copiés dans le répertoire de travail :
- Fichiers CSV définis par les tables de type `OUTPUT`
- Base de données SQLite si `keep_db: true`

Les fichiers temporaires sont créés dans `%TEMP%/SQLite_YYYYMMDD_HHMMSS/` et nettoyés automatiquement.

## Dépannage

### Erreur : "Module non trouvé"
```bash
pip install openpyxl ttkbootstrap pillow
```

### Erreur : "Template SQLite non trouvé"
Vérifier que `sqlite_template_name` dans la config pointe vers un fichier existant.

### Erreur : "CSV source n'existe pas"
Vérifier que le chemin `csv_source` est correct. Utiliser `csv_missing_ok: true` pour ignorer les sources optionnelles.

### Problème d'encodage CSV
Spécifier `csv_encoding` sur la table ou ajuster `input_codec`/`output_codec` dans la section `base`.

## Documentation

- [config_help.md](config_help.md) - Guide complet de configuration

## Auteur

Matthieu Ferrier - [GitHub](https://github.com/Pytre/SQLiteMerger)

## Licence

GNU Affero General Public License (AGPL)
