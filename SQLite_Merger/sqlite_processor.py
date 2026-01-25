import csv
import logging
import re
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Iterator

from config import RunConfig, ProcessContext
from constants import DEFAULT_CODEC
from models import Command, CommandPhase, Table, TableType
from utils import UserInterruptedError, log, get_valid_encoding


# ----------------------------------------------
# dataclasses
# ----------------------------------------------
@dataclass(frozen=True)
class SqlTableInfos:
    """Eléments définissant une table SQL"""

    tbl_name: str
    pragma_infos: tuple[tuple[int, str, str, int, str | None, int]]  # (cid, name, type, notnull, dflt_value, pk)
    names: tuple[str] = field(init=False)  # Calculé automatiquement
    types: tuple[str] = field(init=False)  # Calculé automatiquement
    notnull: tuple[bool] = field(init=False)  # Calculé automatiquement
    dflt_value: tuple[str] = field(init=False)  # Calculé automatiquement
    pk_pos: tuple[int] = field(init=False)  # Calculé automatiquement
    required_col_names: tuple[str] = field(init=False)  # Calculé automatiquement

    def __post_init__(self):
        # object.__setattr__ car la classe est frozen
        object.__setattr__(self, "names", tuple(col[1] for col in self.pragma_infos))
        object.__setattr__(self, "types", tuple(col[2] for col in self.pragma_infos))
        object.__setattr__(self, "notnull", tuple(col[3] == 1 for col in self.pragma_infos))
        object.__setattr__(self, "dflt_value", tuple(col[4] for col in self.pragma_infos))
        object.__setattr__(self, "pk_pos", tuple(col[5] for col in self.pragma_infos))
        object.__setattr__(self, "required_col_names", self._get_required_col_names_auto(self.pragma_infos))

    def get_col_index(self, col_name: str) -> int:
        """Retourne l'index d'une colonne (insensible à la casse, renvoi -1 si introuvable)"""
        return next(
            (i for i, name in enumerate(self.names) if name.upper() == col_name.upper()),
            -1,
        )

    @staticmethod
    def _get_required_col_names_auto(pragma_infos: tuple[tuple[int, str, str, int, str | None, int]]) -> tuple[str]:
        required: list[str] = []

        for col in pragma_infos:
            col_name = col[1]
            col_type = col[2].upper()
            not_null = col[3] == 1
            default_value = col[4]
            is_pk = col[5] > 0
            is_auto_incremented = is_pk and (col_type == "INTEGER")

            # col requise si NOT NULL sans valeur défaut ou Clé pas auto incrementé
            if (not_null and default_value is None) or (is_pk and not is_auto_incremented):
                required.append(col_name)

        return tuple(required)


@dataclass(frozen=True)
class CsvImportConfig:
    """Configuration pour l'import d'un fichier CSV dans une table SQLite

    Attributes:
        tbl_name: Nom de la table SQLite de destination
        tbl_cols_names: Liste des noms de colonnes de la table
        insert_cols_count: Nombre de colonnes insérées
        csv_cols_count: Nombre de colonnes provenant du CSV
        extra_headers: En-têtes supplémentaires (ex: SOURCE)
        extra_values: Valeurs supplémentaires correspondantes
    """

    tbl_infos: SqlTableInfos
    tbl_cols_required_cfg: list[str]
    insert_cols_count: int
    csv_cols_count: int
    extra_headers: list[str]
    extra_values: list[str]


# ----------------------------------------------
# classe
# ----------------------------------------------
class SQLiteProcessor:
    """Classe pour traitement des opérations SQLite"""

    def __init__(self):
        self._tbl_infos_cache: dict[str, SqlTableInfos] = {}
        self._regex_cache: dict[str, re.Pattern] = {}
        self._invalid_regex: set[str] = set()

    # ----------------------------------------------
    # Orchestration principal
    # ----------------------------------------------
    def start_all(self, cfg: RunConfig, ctx: ProcessContext, stop_event: Event):
        """Exécution des commandes SQLite et récupération des fichiers de sortie"""

        cursor: sqlite3.Cursor = None  # assurer l'existence du cursor pour le bloc finally de la connexion

        if stop_event.is_set():
            raise UserInterruptedError("Interruption demandée par l'utilisateur")

        log("Connexion à la base SQLite...", start_timer=True)
        try:
            with sqlite3.connect(ctx.sqlite_db) as conn:
                self._configure_connection(conn)
                cursor = conn.cursor()

                # démarrer les imports
                if stop_event.is_set():
                    raise UserInterruptedError("Interruption demandée par l'utilisateur")
                self.import_data(cursor, cfg, ctx, stop_event)
                conn.commit()  # commit pour assurer l'écriture sur le disque

                # procéder aux exports si non désactivés
                if stop_event.is_set():
                    raise UserInterruptedError("Interruption demandée par l'utilisateur")
                if not cfg.disable_output:
                    self.export_to_csv(conn, cfg, ctx)

                # récupérer les fichiers demandés du dossier temporaire
                self.retrieve_files(cfg, ctx)

        except UserInterruptedError:
            raise
        except Exception:
            log("Problème lors de l'exécution des opérations SQLite", logging.CRITICAL)
            raise
        finally:
            self._cache_clean_up()
            if cursor:
                cursor.close()

    def _configure_connection(self, conn: sqlite3.Connection):
        """Configure la base SQLite pour ajouter le support regex et optimisé l'execution"""

        # Clear des infos en cache de la connexion précédente
        self._cache_clean_up()

        # définition de la fonction REGEXP pour SQLite (utilise le module re de Python)
        def sqlite_regexp(pattern: str, value: str) -> bool:
            if value is None:
                return False
            if pattern not in self._regex_cache:
                try:
                    self._regex_cache[pattern] = re.compile(pattern)  # pour éviter de recompiler à chaque ligne
                except re.error as e:
                    if pattern not in self._invalid_regex:
                        self._invalid_regex.add(pattern)
                        log(f"Erreur regex '{pattern}' : {e}", logging.WARNING)
                    return False
            return self._regex_cache[pattern].search(value) is not None

        # Paramètrage de la base
        conn.execute("PRAGMA synchronous = OFF;")  # Ne pas attendre la confirmation disque
        conn.execute("PRAGMA journal_mode = MEMORY;")  # Journal en mémoire (plus rapide)
        conn.execute("PRAGMA temp_store = MEMORY;")  # Tables temporaires en RAM
        conn.execute("PRAGMA cache_size = -64000;")  # Cache de 64 MB (défaut : 2 MB)
        conn.create_function("REGEXP", 2, sqlite_regexp)  # fonction pour regex dans SQLite

    def _cache_clean_up(self) -> None:
        """Réinitialise les infos en cache"""
        self._tbl_infos_cache.clear()
        self._regex_cache.clear()
        self._invalid_regex.clear()

    # ----------------------------------------------
    # Fonctions génériques sur base SQLite
    # ----------------------------------------------
    def _get_table_infos(self, cursor: sqlite3.Cursor, tbl_name: str) -> SqlTableInfos:
        """Mise en cache la structure de la table"""
        if tbl_name not in self._tbl_infos_cache:
            infos: list[tuple] = cursor.execute(f"PRAGMA table_info({tbl_name});").fetchall()
            if not infos:
                raise ValueError(f"Table '{tbl_name}' introuvable")
            self._tbl_infos_cache[tbl_name] = SqlTableInfos(tbl_name=tbl_name, pragma_infos=tuple(infos))

        return self._tbl_infos_cache[tbl_name]

    def _sql_exec_commands(self, cursor: sqlite3.Cursor, commands: list[Command]):
        """Execute des commandes d'une liste de dict avec clé sql (string) et clé commit (bool)"""
        for cmd in commands:
            if not cmd.sql:
                continue
            try:
                cursor.execute(cmd.sql)
                if cmd.commit:
                    cursor.connection.commit()
            except sqlite3.Error as e:
                log(f"Erreur SQL sur commande '{cmd.sql}' : {e}", logging.ERROR)

    # ----------------------------------------------
    # Import : orchestration
    # ----------------------------------------------
    def import_data(self, cursor: sqlite3.Cursor, cfg: RunConfig, ctx: ProcessContext, stop_event: Event):
        log("Opérations d'import : initialisation...", start_timer=True)
        self._sql_import_init(cursor, cfg)
        self._sql_import_variables(cursor, cfg, stop_event)
        log("Opérations d'import : chargement des fichiers...", start_timer=True)
        self._sql_import_from_cfg(cursor, cfg, stop_event)  # passage stop_event pour pouvoir stopper
        self._sql_import_from_ctx(cursor, ctx, stop_event)  # passage stop_event pour pouvoir stopper
        log("Opérations d'import : finalisation...", start_timer=True)
        self._sql_import_finalize(cursor, cfg, stop_event)  # passage stop_event pour pouvoir stopper

    def _sql_import_init(self, cursor: sqlite3.Cursor, cfg: RunConfig):
        """Phase d'initialisation de la base"""
        commands: list[Command] = [cmd for cmd in cfg._sql_commands if cmd.phase is CommandPhase.INIT]
        self._sql_exec_commands(cursor, commands)

    def _sql_import_variables(self, cursor: sqlite3.Cursor, cfg: RunConfig, stop_event: Event):
        """Met à jour les variables de configuration dans la table Variables de la base SQLite"""
        if stop_event.is_set():
            raise UserInterruptedError("Interruption demandée par l'utilisateur")

        for var in cfg._sql_variables:
            if var.sql_table:
                sql = f"UPDATE {var.sql_table} SET {var.sql_set_col} = ? WHERE {var.sql_where_col} = ?;"
                cursor.execute(sql, (var.value, var.sql_name))

    def _sql_import_from_cfg(self, cursor: sqlite3.Cursor, cfg: RunConfig, stop_event: Event):
        """Import des tables générées depuis le fichier Excel (DIM + FACT)"""

        def import_csv(type: TableType):
            for table in cfg._sql_tables:
                # uniquement types correspondant
                if table.type is not type or not table.import_filepath:
                    continue
                if not table.sql_name:
                    raise ValueError(f"Table SQL non déclaré pour import de '{table.csv_name}'")
                if stop_event.is_set():
                    raise UserInterruptedError("Interruption demandée par l'utilisateur")

                self._import_csv_to_table(cursor, table.import_filepath, table)

        import_csv(TableType.DIM)
        import_csv(TableType.FACT)

    def _sql_import_from_ctx(self, cursor: sqlite3.Cursor, ctx: ProcessContext, stop_event: Event):
        """Import des fichiers récupérés à partir de dossiers d'import"""

        for table in ctx.fact_tables:
            if stop_event.is_set():
                raise UserInterruptedError("Interruption demandée par l'utilisateur")
            self._import_csv_to_table(cursor, table.import_filepath, table)

    def _sql_import_finalize(self, cursor: sqlite3.Cursor, cfg: RunConfig, stop_event: Event):
        """Traitements finaux"""
        if stop_event.is_set():
            raise UserInterruptedError("Interruption demandée par l'utilisateur")

        commands: list[Command] = [cmd for cmd in cfg._sql_commands if cmd.phase is CommandPhase.POST_IMPORTS]
        self._sql_exec_commands(cursor, commands)

    # ----------------------------------------------
    # Import : helpers pour CSV
    # --------------------------------------------
    def _import_csv_to_table(self, cursor: sqlite3.Cursor, csv_file: Path, tbl: Table):
        """Importe un fichier CSV dans une table SQLite"""
        if not isinstance(csv_file, Path) or not csv_file.exists():
            log(f"Fichier CSV pour import dans la base SQLite non trouvé : {csv_file}", logging.WARNING)
            return

        # Infos de la table dans laquelle importer
        tbl_infos: SqlTableInfos = self._get_table_infos(cursor, tbl.sql_name)
        col_names: list[str] = tbl_infos.names

        # Détermination si l'info de la source doit être ajoutée
        add_source: bool = True if tbl.col_source else False
        if add_source:
            source_idx: int = next(
                (i for i, name in enumerate(col_names) if name.upper() == tbl.col_source.upper()),
                -1,
            )
            if source_idx == -1:
                add_source = False
                log(f"Info de la source non ajoutée pour l'import de '{csv_file.name}'", logging.WARNING)
                log(f"La colonne '{tbl.col_source}' n'existe pas dans '{tbl.sql_name}'.", logging.WARNING)
            if source_idx != len(col_names) - 1:
                add_source = False
                log(f"Info de la source non ajoutée pour l'import de '{csv_file.name}'", logging.WARNING)
                log(f"La colonne source doit être la dernière dans la table '{tbl.sql_name}'.", logging.WARNING)

        # Traitement du fichier CSV à importer
        with self._csv_read_file(csv_file, encoding=tbl.csv_encoding) as (fieldnames, rows):
            cols_count_offset = -1 if add_source else 0

            field_nb = len(fieldnames) if fieldnames else 0
            csv_cols_count = min(field_nb, len(col_names) + cols_count_offset)
            insert_cols_count = len(col_names) if add_source else csv_cols_count
            csv_add_count = max(len(col_names) - csv_cols_count, 0)

            extra_headers, extra_values = [], []
            if add_source:
                extra_headers = [""] * (csv_add_count - 1) + [tbl_infos.names[-1]]
                extra_values = [""] * (csv_add_count - 1) + [csv_file.name]

            cfg = CsvImportConfig(
                tbl_infos=tbl_infos,
                tbl_cols_required_cfg=tbl.required_cols,
                csv_cols_count=csv_cols_count,
                insert_cols_count=insert_cols_count,
                extra_headers=extra_headers,
                extra_values=extra_values,
            )

            # Préparation de la requête SQL
            col_to_insert = ", ".join([f'"{col}"' for col in col_names[:insert_cols_count]])
            placeholders = ", ".join(["?"] * insert_cols_count)
            sql = f"INSERT INTO {tbl.sql_name} ({col_to_insert}) VALUES ({placeholders})"

            try:
                rows_to_insert = (
                    row for row in map(lambda row_dict: self._csv_prepare_row(row_dict, cfg), rows) if row is not None
                )
                cursor.executemany(sql, rows_to_insert)
            except Exception as e:
                cursor.connection.rollback()
                raise Exception(f"Erreur lors de l'import de '{csv_file.name}' dans '{tbl.sql_name}' : {e}")

    @contextmanager
    def _csv_read_file(self, csv_file: Path, encoding: str = "") -> Iterator[tuple[list[str], csv.DictReader]]:
        """Context manager pour lire un fichier CSV en testant plusieurs formats d'encodage"""
        # Encodages à tester, du plus strict au moins strict
        encs_to_test: list[str] = ["utf-8-sig", "utf-8", "cp1252", "iso-8859-1"]

        # Si encodage fourni alors on le place à utiliser en premier
        dflt_enc = encoding.lower() if encoding and get_valid_encoding(encoding) else DEFAULT_CODEC
        if dflt_enc in encs_to_test:
            encs_to_test.remove(dflt_enc)
        encs_to_test.insert(0, dflt_enc)

        # Test encoding sur premières lignes pour valider qu'on puisse bien faire des yield sans plantage
        selected_enc: str = ""
        nb_mega: int = 10
        for enc in encs_to_test:
            try:
                with open(csv_file, "r", encoding=enc, newline="") as f:
                    f.read(nb_mega * 1024 * 1024)
                selected_enc = enc
                break
            except (UnicodeDecodeError, LookupError):
                continue

        # Sélection de l'encodage à utiliser
        if not selected_enc:
            selected_enc = dflt_enc
            log(
                f"Aucun encodage n'a fonctionné sur l'échantillon test pour lire '{csv_file.name}'."
                + f"Utilisation de '{dflt_enc}' en remplaçant les erreurs de décodage !",
                logging.WARNING,
            )

        # Réouverture pour lire depuis le début pour passer csv_reader
        with open(csv_file, "r", encoding=selected_enc, newline="", errors="replace") as f:
            csv_reader = csv.DictReader(f, delimiter=";")
            fieldnames = csv_reader.fieldnames
            yield fieldnames, csv_reader

    def _csv_prepare_row(self, row_dict: dict, cfg: CsvImportConfig) -> list[str] | None:
        """Prépare une ligne provenant d'un CSV pour import dans SQLite"""
        row_values: list[str] = list(row_dict.values())
        tbl_infos: SqlTableInfos = cfg.tbl_infos

        # Filtrer lignes vides
        if all(v == "" for v in row_values[: cfg.insert_cols_count]):
            return None

        # Filtrer lignes sans valeurs dans les colonnes requises dans le fichier de config
        for col in cfg.tbl_cols_required_cfg:
            idx = tbl_infos.get_col_index(col)
            if idx < 0:
                raise ValueError(f"Colonne '{col}' requise pour table '{cfg.tbl_name}' n'existe pas !")
            if row_values[idx] is None or row_values[idx].strip() == "":
                return None

        # Nettoyer et construire
        row_clean = [
            self._csv_clean_up_value(tbl_infos.types[i], val) for i, val in enumerate(row_values[: cfg.csv_cols_count])
        ] + cfg.extra_values

        return row_clean

    @staticmethod
    def _csv_clean_up_value(col_type: str, value: str) -> str | int | float | None:
        """Nettoie une valeur provenant d'un CSV pour import dans SQLite
        cf doc SQLite : https://sqlite.org/datatype3.html"""
        type_upper = col_type.upper()

        # si pas de valeur
        if value is None or value.strip() == "":
            return value  # en principe on devrait retourné None mais potentiellement bloquant

        # 1. Affinity INTEGER
        if any(p in type_upper for p in ("INT", "BIT", "BOOL")):
            try:
                clean_value: str = "0" if "E" in value.upper() else value.replace(" ", "").replace(",", ".")
                return int(clean_value)
            except ValueError:
                return value

        # 2. Affinity TEXT ("CHAR", "CLOB", "TEXT") + 3. Affinity BLOB ("BLOB")
        if any(p in type_upper for p in ("CHAR", "CLOB", "TEXT", "BLOB")):
            return value

        # 4. Affinity REAL ("REAL", "FLOA", "DOUB") + 5. Affinity NUMERIC (tous les autres cas)
        try:
            clean_value: str = "0" if "E" in value.upper() else value.replace(" ", "").replace(",", ".")
            return float(clean_value)
        except ValueError:
            return value

    # ----------------------------------------------
    # Export et récup des fichiers
    # ----------------------------------------------
    def export_to_csv(self, conn: sqlite3.Connection, cfg: RunConfig, ctx: ProcessContext):
        """Exports vers CSV"""

        log("Opérations d'export : création des fichiers...", start_timer=True)
        tables: list[Table] = [table for table in cfg._sql_tables if table.type is TableType.OUTPUT]
        for table in tables:
            csv_encoding = table.csv_encoding
            cursor = conn.execute(f"SELECT * FROM {table.sql_name};")
            file_path: Path = table.get_export_path(cfg, ctx)
            with open(file_path, "w", encoding=csv_encoding, errors="replace", newline="") as f:
                writer = csv.writer(f, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writerow([desc[0] for desc in cursor.description])
                writer.writerows(cursor)

    def retrieve_files(self, cfg: RunConfig, ctx: ProcessContext):
        """Récupère les fichiers de sortie depuis le dossier temporaire"""
        files: list[Path] = []

        # Fichiers extrait à récupérer
        if not cfg.disable_output:
            tables: list[Table] = [table for table in cfg._sql_tables if table.type is TableType.OUTPUT]
            files = [table.get_export_path(cfg, ctx) for table in tables]

        # Récupération de la base si demandé
        if cfg.keep_db:
            files.append(ctx.sqlite_db)

        # Copie des fichiers
        if files:
            log("Opérations d'export : récupération des fichiers...", stop_timer=True)
        for src in files:
            dst = cfg.default_folder / src.name
            if src.exists():
                shutil.copy(src, dst)
                log(" " * 8 + src.name)
            else:
                log(" " * 8 + f"⚠️ Fichier non trouvé : {src}", logging.WARNING)
