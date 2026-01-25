# Guide de configuration - SQLite Merger

Ce document décrit comment configurer le fichier `SQLite_Merger.cfg` (format JSON).

> **Note :** Le backslash `\` est le caractère d'échappement en JSON. Pour les chemins Windows, utiliser `\\` ou `/`.

---

## Structure générale

```json
{
  "base": { ... },
  "sql_tables": [ ... ],
  "sql_variables": [ ... ],
  "sql_commands": [ ... ]
}
```

---

## Section `base`

Options générales de l'application.

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `sqlite_template_name` | string | `""` | Nom du fichier template SQLite |
| `input_codec` | string | `"utf-8-sig"` | Encodage par défaut des CSV sources existants |
| `output_codec` | string | `"cp1252"` | Encodage par défaut des fichiers exportés |
| `disable_output` | bool | `false` | Désactive l'export des fichiers CSV |
| `keep_db` | bool | `true` | Conserve la base SQLite après traitement |
| `kept_db_name` | string | `""` | Nom de la base conservée (supporte les variables) |
| `copy_csv_to_temp` | bool | `false` | Copie les CSV sources dans le dossier temporaire |

---

## Section `sql_tables`

Liste des tables à gérer. Trois modes d'utilisation :
- **Import Excel** : crée un CSV depuis un onglet Excel
- **Import CSV source** : importe depuis un fichier ou dossier existant
- **Export** : exporte les résultats vers un fichier CSV

### Paramètres communs (toutes tables)

| Paramètre | Obligatoire | Type | Description |
|-----------|:-----------:|------|-------------|
| `table_id` | Non | string | Identifiant unique (recommandé pour debug) |
| `type` | **Oui** | string | Type : `"DIM"`, `"FACT"` ou `"OUTPUT"` |
| `sql_name` | **Oui** | string | Nom de la table dans SQLite |

### Paramètres optionnels communs (import uniquement)

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `col_source` | string | `""` | Nom de colonne pour stocker le nom du fichier source |
| `required_cols` | array | `[]` | Liste des colonnes requises pour valider l'import |

---

### Mode : Import depuis Excel

Pour créer un CSV temporaire à partir d'un onglet du fichier `Tables_Infos.xlsx`.

| Paramètre | Obligatoire | Type | Description |
|-----------|:-----------:|------|-------------|
| `excel_name` | **Oui** | string | Nom de l'onglet Excel source |
| `csv_name` | **Oui** | string | Nom du fichier CSV généré |
| `csv_encoding` | Non | string | Encodage du fichier CSV (défaut : `cp1252`) |

**Exemple :**
```json
{
  "table_id": "dim_clients",
  "type": "DIM",
  "sql_name": "Clients",
  "excel_name": "CLIENTS",
  "csv_name": "clients.csv"
}
```

---

### Mode : Import depuis fichier/dossier CSV

Pour importer depuis des fichiers CSV existants.

| Paramètre | Obligatoire | Type | Description |
|-----------|:-----------:|------|-------------|
| `csv_source` | **Oui** | string | Chemin vers fichier ou dossier (supporte les variables) |
| `csv_pattern_regex` | Non | string | Regex pour filtrer les fichiers (défaut : `.+\.csv$`) |
| `csv_encoding` | Non | string | Encodage du fichier (défaut : valeur de `input_codec`) |
| `csv_missing_ok` | Non | bool | Ne pas alerter si source introuvable (défaut : `false`) |

#### Cas 1 : Fichier unique

```json
{
  "table_id": "balance_n",
  "type": "FACT",
  "sql_name": "Balance",
  "csv_source": "C:/Data/balance_{periode}.csv"
}
```

#### Cas 2 : Dossier avec multiples fichiers

Tous les fichiers du dossier correspondant au `csv_pattern_regex` seront importés.

```json
{
  "table_id": "balances_folder",
  "type": "FACT",
  "sql_name": "Balance",
  "csv_source": "C:/Data/Balances/",
  "csv_pattern_regex": "^BAL_.*\\.csv$",
  "col_source": "fichier_source"
}
```

> **Encodage :** Par défaut `utf-8-sig` (valeur de `input_codec`). Spécifier `csv_encoding` pour override.

---

### Mode : Export (OUTPUT)

Pour exporter les données vers un fichier CSV.

| Paramètre | Obligatoire | Type | Description |
|-----------|:-----------:|------|-------------|
| `csv_name` | **Oui** | string | Nom du fichier exporté (supporte les variables) |
| `csv_encoding` | Non | string | Encodage du fichier (défaut : valeur de `output_codec`) |

**Exemple :**
```json
{
  "table_id": "export_resultat",
  "type": "OUTPUT",
  "sql_name": "Resultat",
  "csv_name": "Resultat_{periode}_{timestamp}.csv"
}
```

> **Encodage :** Par défaut `cp1252` (valeur de `output_codec`). Spécifier `csv_encoding` pour override.

---

## Encodage des fichiers - Récapitulatif

| Source | Encodage par défaut | Modifiable via |
|--------|---------------------|----------------|
| Excel (auto-généré) | `cp1252` | `csv_encoding` (table) |
| CSV source existant | `utf-8-sig` | `input_codec` (global) ou `csv_encoding` (table) |
| Export OUTPUT | `cp1252` | `output_codec` (global) ou `csv_encoding` (table) |

**Comportement détaillé :**

- **Excel** : Par défaut `cp1252`. Modifiable via `csv_encoding` sur la table.
- **CSV source** : Utilise `csv_encoding` de la table si défini, sinon `input_codec` de la section base, sinon `utf-8-sig`.
- **OUTPUT** : Utilise `csv_encoding` de la table si défini, sinon `output_codec` de la section base, sinon `cp1252`.

> **Note :** Si un encodage invalide est spécifié, un warning est affiché et l'encodage par défaut est utilisé.

---

## Section `sql_variables`

Variables utilisables dans les chemins, noms de fichiers et requêtes SQL.

| Paramètre | Obligatoire | Type | Description |
|-----------|:-----------:|------|-------------|
| `sql_name` | **Oui** | string | Nom de la variable (utilisé comme `{nom}` dans les chemins) |
| `ui_label` | Non | string | Label affiché dans l'interface |
| `level` | Non | string | Niveau d'accès : `"user"`, `"advanced"`, `"internal"` |
| `default` | Non | string | Valeur par défaut (supporte les expressions Calculator) |
| `regex_ctrl` | Non | string | Regex de validation de la valeur |
| `optional` | Non | bool | `true` si la variable peut être vide |

### Paramètres pour import SQL

Si la variable doit être insérée dans une table :

| Paramètre | Obligatoire* | Type | Description |
|-----------|:------------:|------|-------------|
| `sql_table` | Oui* | string | Nom de la table cible |
| `sql_set_col` | Oui* | string | Colonne à mettre à jour |
| `sql_where_col` | Oui* | string | Colonne pour la condition WHERE |

*Obligatoire si `sql_table` est défini.

**Exemple :**
```json
{
  "sql_name": "periode",
  "ui_label": "Période comptable",
  "level": "user",
  "default": "=YYYYMM(-1)",
  "regex_ctrl": "^[0-9]{6}$"
}
```

### Niveaux de variables

| Niveau | Description |
|--------|-------------|
| `user` | Affiché en priorité dans la fenêtre des variables |
| `advanced` | Affiché après les variables `user` dans la fenêtre des variables |
| `internal` | Masqué par défaut, accessible via le bouton "+" dans la fenêtre des variables |

> Les variables `user` et `advanced` sont affichées par défaut. Les variables `internal` sont masquées mais peuvent être affichées et modifiées via le bouton "+" (avec un avertissement).

---

## Section `sql_commands`

Commandes SQL à exécuter pendant le traitement.

| Paramètre | Obligatoire | Type | Description |
|-----------|:-----------:|------|-------------|
| `phase` | **Oui** | string | Quand exécuter : `"init"` ou `"post_imports"` |
| `sql` | **Oui** | string | Requête SQL à exécuter |
| `commit` | Non | bool | Effectuer un COMMIT après (défaut : `false`) |

### Phases d'exécution

| Phase | Description |
|-------|-------------|
| `init` | Avant les imports (initialisation, nettoyage) |
| `post_imports` | Après tous les imports (calculs, agrégations) |

**Exemple :**
```json
{
  "phase": "post_imports",
  "sql": "UPDATE Balance SET periode = '{periode}' WHERE periode IS NULL",
  "commit": true
}
```

---

## Variables disponibles dans les chemins

Les placeholders `{nom}` sont remplacés par leurs valeurs :

| Variable | Description |
|----------|-------------|
| `{timestamp}` | Horodatage de l'exécution (format `YYYYMMDD_HHMMSS`) |
| `{nom_variable}` | Valeur de la variable SQL correspondante |

**Exemple :**
```
"csv_source": "C:/Data/{periode}/balance.csv"
"csv_name": "Export_{periode}_{timestamp}.csv"
```

---

## Exemple complet

```json
{
  "base": {
    "sqlite_template_name": "template.sqlite",
    "input_codec": "utf-8-sig",
    "output_codec": "cp1252",
    "keep_db": true,
    "kept_db_name": "Database_{periode}.sqlite"
  },
  "sql_variables": [
    {
      "sql_name": "periode",
      "ui_label": "Période",
      "level": "user",
      "default": "=YYYYMM(-1)",
      "regex_ctrl": "^[0-9]{6}$"
    }
  ],
  "sql_tables": [
    {
      "table_id": "dim_plan",
      "type": "DIM",
      "sql_name": "Plan",
      "excel_name": "PLAN_COMPTABLE",
      "csv_name": "plan.csv"
    },
    {
      "table_id": "fact_balance",
      "type": "FACT",
      "sql_name": "Balance",
      "csv_source": "C:/Balances/{periode}/",
      "csv_pattern_regex": "^BAL_.*\\.csv$",
      "col_source": "fichier"
    },
    {
      "table_id": "export_resultat",
      "type": "OUTPUT",
      "sql_name": "Resultat",
      "csv_name": "Resultat_{periode}.csv"
    }
  ],
  "sql_commands": [
    {
      "phase": "post_imports",
      "sql": "DELETE FROM Balance WHERE montant = 0",
      "commit": true
    }
  ]
}
```
