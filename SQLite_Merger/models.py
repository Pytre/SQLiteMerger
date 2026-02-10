from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from calculator import Calculator
from constants import DEFAULT_CODEC, INPUT_CODEC, OUTPUT_CODEC
from utils import log, get_valid_encoding

if TYPE_CHECKING:
    from config import RunConfig, ProcessContext


# ----------------------------------------------
# Table
# ----------------------------------------------
class TableType(Enum):
    """Types de tables / mapping JSON"""

    UNKNOWN = "UNKNOWN"
    DIM = "DIM"
    FACT = "FACT"
    OUTPUT = "OUTPUT"


class TableConfigAttr(Enum):
    """TableConfig attributs mapping avec clé JSON pour chargement/sauvegarde config"""

    ID = "table_id"
    TYPE = "type"
    SQL_NAME = "sql_name"
    EXCEL_NAME = "excel_name"
    CSV_NAME = "csv_name"
    CSV_SOURCE = "csv_source"
    CSV_PATTERN_REGEX = "csv_pattern_regex"
    CSV_ENCODING = "csv_encoding"
    CSV_MISSING_OK = "csv_missing_ok"
    COL_SOURCE = "col_source"
    REQUIRED_COLS = "required_cols"


@dataclass
class TableConfig:
    """Eléments de configuration d'une table SQL"""

    ID: str = ""
    TYPE: str | TableType = ""
    SQL_NAME: str = ""
    EXCEL_NAME: str = ""
    CSV_NAME: str = ""
    CSV_SOURCE: Path | None = None
    CSV_PATTERN_REGEX: re.Pattern | str = ""
    CSV_ENCODING: str = ""
    CSV_MISSING_OK: bool = False
    COL_SOURCE: str = ""
    REQUIRED_COLS: list[str] = field(default_factory=list)


class Table:
    """Classe information table avec type et correspondances SQLite, Excel et CSV.
    Si colonne source indiquée alors le nom du fichier CSV sera rajouté lors de l'import."""

    @classmethod
    def dict_to_config(cls, tbl_dict: dict) -> TableConfig:
        """Transformation d'un dictionnaire en config Table"""
        return TableConfig(
            ID=tbl_dict.get(TableConfigAttr.ID.value, ""),
            TYPE=tbl_dict.get(TableConfigAttr.TYPE.value, TableType.UNKNOWN),
            SQL_NAME=tbl_dict.get(TableConfigAttr.SQL_NAME.value, ""),
            EXCEL_NAME=tbl_dict.get(TableConfigAttr.EXCEL_NAME.value, ""),
            CSV_NAME=tbl_dict.get(TableConfigAttr.CSV_NAME.value, ""),
            CSV_SOURCE=tbl_dict.get(TableConfigAttr.CSV_SOURCE.value, None),
            CSV_PATTERN_REGEX=tbl_dict.get(TableConfigAttr.CSV_PATTERN_REGEX.value, ""),
            CSV_ENCODING=tbl_dict.get(TableConfigAttr.CSV_ENCODING.value, ""),
            CSV_MISSING_OK=tbl_dict.get(TableConfigAttr.CSV_MISSING_OK.value, False),
            COL_SOURCE=tbl_dict.get(TableConfigAttr.COL_SOURCE.value, ""),
            REQUIRED_COLS=tbl_dict.get(TableConfigAttr.REQUIRED_COLS.value, []),
        )

    def __init__(self, cfg: TableConfig):
        self.id: str = cfg.ID
        self.type: TableType = self._set_type(cfg.TYPE)
        self.sql_name: str = cfg.SQL_NAME
        self.excel_name: str = cfg.EXCEL_NAME
        self.csv_name: str = cfg.CSV_NAME
        self.csv_source: Path | None = self._set_csv_source(cfg.CSV_SOURCE)
        self.csv_pattern_regex: re.Pattern = self._set_csv_regex(cfg.CSV_PATTERN_REGEX)
        self.csv_encoding: str = self._set_encoding(encoding=cfg.CSV_ENCODING)
        self.csv_missing_ok: bool = cfg.CSV_MISSING_OK
        self.col_source: str = cfg.COL_SOURCE
        self.required_cols: list = cfg.REQUIRED_COLS

        self.import_filepath: Path | None = None

        self._check_init()

    def _check_init(self):
        # contrôle si sql_name présent
        if not self.sql_name:
            log(f"Table '{self.sql_name}' ne définit pas sql_name", logging.ERROR)

        attr_to_create_from_xl = (self.csv_name, self.excel_name)

        # contrôle que source n'est pas un fichier et un dossier
        if self.csv_source and any(attr_to_create_from_xl):
            log(
                f"Table '{self.sql_name}' ne peut avoir à la fois en source excel et un fichier/dossier", logging.ERROR
            )

        # contrôle si csv_name que excel_name soit aussi alimenté
        if self.type is not TableType.OUTPUT and any(attr_to_create_from_xl) and not all(attr_to_create_from_xl):
            log(
                f"Table '{self.sql_name}' ne peut pas définir uniquement csv_name sans excel_name et inversement",
                logging.ERROR,
            )

        # contrôle si csv_name fourni pour type table Output
        if self.type is TableType.OUTPUT and not self.csv_name:
            log(f"Table '{self.sql_name}' est de type output et doit obligatoirement définir csv_name", logging.ERROR)

    def _set_type(self, tbl_type: str | TableType) -> TableType:
        """Renvoi un TableType valide"""
        if isinstance(tbl_type, TableType):
            return tbl_type
        else:
            try:
                return TableType(tbl_type)
            except ValueError:
                log(f"Objet Table avec type invalide ('{tbl_type}') !", logging.CRITICAL)
                return TableType.UNKNOWN

    def _set_csv_source(self, filename: str | None) -> Path | None:
        """Retourne un Path pour les fichiers/dossiers préexistants sinon renvoi None"""
        if not filename:
            return None
        elif self.type is TableType.OUTPUT or self.excel_name:
            log(f"Table '{self.id}' csv_source non autorisé avec type output ou csv_name", logging.WARNING)
            return None

        return Path(filename)

    def _set_csv_regex(self, pattern: str | re.Pattern) -> re.Pattern:
        if isinstance(pattern, re.Pattern):
            return pattern

        if not pattern:
            return re.compile(r".+\.csv$")

        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            log(f"Table '{self.id}' utilise un pattern regex invalide '{pattern}': {e}", logging.WARNING)
            log("Tous les fichiers csv seront par défaut acceptés", logging.WARNING)

        return re.compile(r".+\.csv$")

    def _set_encoding(self, encoding: str = "") -> str:
        """Renvoi un encodage valide"""
        codec_warn: bool = True if encoding else False  # N'avertir que si un format d'encodage était fourni

        # si encoding pas ok alors détermination d'une valeur par défaut à utiliser
        if not get_valid_encoding(encoding, warn=codec_warn):
            if self.excel_name:
                encoding = DEFAULT_CODEC
            elif self.type is TableType.OUTPUT:
                encoding = OUTPUT_CODEC
            else:
                encoding = INPUT_CODEC

            if codec_warn:
                log(f"Encodage table '{self.sql_name}' non valide. Utilisation de '{encoding}'.", logging.WARNING)

        return encoding

    @property
    def from_excel(self) -> bool:
        """Indique si le CSV d'une table est auto généré à partir d'excel"""
        if self.type is TableType.OUTPUT:
            return False

        return True if self.excel_name and self.csv_name else False

    @property
    def from_csv_source(self) -> bool:
        """Indique si une table est un fichier ou dossier pré existant"""
        if self.type is TableType.OUTPUT:
            return False

        return True if self.csv_source else False

    def get_cfg(self) -> TableConfig:
        """Renvoi un objet config correspondant à l'instance"""
        return TableConfig(
            ID=self.id,
            TYPE=self.type,
            SQL_NAME=self.sql_name,
            EXCEL_NAME=self.excel_name,
            CSV_NAME=self.csv_name,
            CSV_SOURCE=self.csv_source,
            CSV_PATTERN_REGEX=self.csv_pattern_regex,
            CSV_ENCODING=self.csv_encoding,
            CSV_MISSING_OK=self.csv_missing_ok,
            COL_SOURCE=self.col_source,
            REQUIRED_COLS=self.required_cols,
        )

    def get_export_path(self, cfg: RunConfig, ctx: ProcessContext) -> Path:
        """Génère le chemin d'export spécifique pour les exports avec expansion des variables"""
        if self.type is not TableType.OUTPUT:
            return None

        return ctx.temp_dir / expand_vars(self.csv_name, cfg, ctx)


# ----------------------------------------------
# Variable
# ----------------------------------------------
class VariableLevel(Enum):
    """Niveau d'accès de la variable"""

    USER = "user"  # affiché dans la fenêtre principal
    ADVANCED = "advanced"  # afficher dans la fenêtre avancée
    INTERNAL = "internal"  # jamais affiché

    @property
    def priority(self) -> int:
        """Définit l'ordre de tri"""
        mapping = {VariableLevel.USER: 1, VariableLevel.ADVANCED: 2, VariableLevel.INTERNAL: 3}
        return mapping.get(self, 99)


class VariableConfigAttr(Enum):
    """Variable SQL attributs mapping avec clé JSON pour chargement/sauvegarde config"""

    UI_LABEL = "ui_label"
    SQL_NAME = "sql_name"
    SQL_TABLE = "sql_table"
    SQL_SET_COL = "sql_set_col"
    SQL_WHERE_COL = "sql_where_col"
    LEVEL = "level"
    DEFAULT = "default"
    REGEX_CTRL = "regex_ctrl"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class VariableConfig:
    """Eléments de configuration d'une variable SQL"""

    SQL_NAME: str = ""
    UI_LABEL: str = ""
    SQL_TABLE: str = ""
    SQL_SET_COL: str = ""
    SQL_WHERE_COL: str = ""
    LEVEL: str | VariableLevel = ""
    DEFAULT: str = ""
    REGEX_CTRL: str = ""
    OPTIONAL: bool = False


class Variable:
    """Classe représentant une variable de configuration. Les Variables sont utilisées pour :
    - Etre importer dans leurs tables si sql_table est défini
    - Stocker des valeurs configurables
    - Remplacer des placeholders dans les noms de fichiers
    - Valider les entrées utilisateur via regex_ctrl
    """

    calc: Calculator = Calculator()

    @classmethod
    def dict_to_config(cls, tbl_dict: dict) -> VariableConfig:
        """Transformation d'un dictionnaire en config Variable"""
        return VariableConfig(
            SQL_NAME=tbl_dict.get(VariableConfigAttr.SQL_NAME.value, ""),
            UI_LABEL=tbl_dict.get(VariableConfigAttr.UI_LABEL.value, ""),
            SQL_TABLE=tbl_dict.get(VariableConfigAttr.SQL_TABLE.value, ""),
            SQL_SET_COL=tbl_dict.get(VariableConfigAttr.SQL_SET_COL.value, ""),
            SQL_WHERE_COL=tbl_dict.get(VariableConfigAttr.SQL_WHERE_COL.value, ""),
            LEVEL=tbl_dict.get(VariableConfigAttr.LEVEL.value, ""),
            DEFAULT=tbl_dict.get(VariableConfigAttr.DEFAULT.value, ""),
            REGEX_CTRL=tbl_dict.get(VariableConfigAttr.REGEX_CTRL.value, ""),
            OPTIONAL=tbl_dict.get(VariableConfigAttr.OPTIONAL.value, ""),
        )

    def __init__(self, cfg: VariableConfig):
        self.sql_name: str = cfg.SQL_NAME
        self.ui_label: str = cfg.UI_LABEL
        self.sql_table: str = cfg.SQL_TABLE
        self.sql_set_col: str = cfg.SQL_SET_COL
        self.sql_where_col: str = cfg.SQL_WHERE_COL
        self.level: VariableLevel = self._set_level(cfg.LEVEL)
        self.default: str = Variable.calc.evaluate(cfg.DEFAULT)
        self.value: str = self.default  # initialiser de la valeur par défaut
        self.regex_ctrl: re.Pattern = re.compile(cfg.REGEX_CTRL) if cfg.REGEX_CTRL else re.compile(".*")
        self.optional: bool = cfg.OPTIONAL

        self._check_init()

    def _set_level(self, level: str | VariableLevel) -> VariableLevel:
        """Initialise le level de la variable"""
        if isinstance(level, VariableLevel):
            return level
        else:
            try:
                return VariableLevel(level)
            except ValueError:
                log(
                    f"Objet Variable avec level invalide ('{level}') ! "
                    + f"Pris en tant que '{VariableLevel.ADVANCED.value}' par défaut",
                    logging.WARNING,
                )
                return VariableLevel.ADVANCED

    def _check_init(self):
        """Contrôle l'initialisation correcte de set_col et where_col si sql_table a été donné"""
        if self.sql_table and not self.sql_set_col:
            raise ValueError(f"Variable '{self.sql_name}' : {VariableConfigAttr.SQL_SET_COL.value} requis")
        if self.sql_table and not self.sql_where_col:
            raise ValueError(f"Variable '{self.sql_name}' : {VariableConfigAttr.SQL_WHERE_COL.value} requis")

    def get_cfg(self) -> VariableConfig:
        """Renvoi un objet config correspondant à l'instance"""
        return VariableConfig(
            SQL_NAME=self.sql_name,
            UI_LABEL=self.ui_label,
            SQL_TABLE=self.sql_table,
            SQL_SET_COL=self.sql_set_col,
            SQL_WHERE_COL=self.sql_where_col,
            LEVEL=self.level,
            DEFAULT=self.default,
            REGEX_CTRL=self.regex_ctrl.pattern,
            OPTIONAL=self.optional,
        )

    def value_is_valid(self, empty_is_ok: bool = False) -> bool:
        """Validation que la valeur respecte bien le regex de ctrl"""
        if empty_is_ok and not self.value:
            return True
        elif not self.optional and not self.value:
            return False
        elif self.regex_ctrl.match(self.value) is None:
            return False

        return True


# ----------------------------------------------
# Command
# ----------------------------------------------
class CommandPhase(Enum):
    """Quand une commande doit s'executer"""

    UNKNOWN = "UNKNOWN"
    INIT = "init"
    POST_IMPORTS = "post_imports"


class CommandConfigAttr(Enum):
    """Commande SQL attributs mapping avec clé JSON pour chargement/sauvegarde config"""

    PHASE = "phase"
    SQL = "sql"
    COMMIT = "commit"


@dataclass
class CommandConfig:
    """Eléments de configuration d'une commande SQL"""

    PHASE: str | CommandPhase = None
    SQL: str = ""
    COMMIT: bool = False


class Command:
    """Classe information commande SQL"""

    @classmethod
    def dict_to_config(cls, tbl_dict: dict) -> CommandConfig:
        """Transformation d'un dictionnaire en config commande"""
        return CommandConfig(
            PHASE=tbl_dict.get(CommandConfigAttr.PHASE.value, CommandPhase.UNKNOWN),
            SQL=tbl_dict.get(CommandConfigAttr.SQL.value, ""),
            COMMIT=tbl_dict.get(CommandConfigAttr.COMMIT.value, False),
        )

    def __init__(self, cfg: CommandConfig):
        self.phase: CommandPhase = None
        self.sql: str = cfg.SQL
        self.commit: bool = cfg.COMMIT

        if isinstance(cfg.PHASE, CommandPhase):
            self.phase = cfg.PHASE
        else:
            try:
                self.phase = CommandPhase(cfg.PHASE)
            except ValueError:
                log(f"Objet Command avec phase invalide ('{cfg.PHASE}') !", logging.CRITICAL)
                self.phase = CommandPhase.UNKNOWN

    def get_cfg(self) -> CommandConfig:
        """Renvoi un objet config correspondant à l'instance"""
        return CommandConfig(
            PHASE=self.phase,
            SQL=self.sql,
            COMMIT=self.commit,
        )


# ----------------------------------------------
# Fonction helper
# ----------------------------------------------
def expand_vars(text: str, cfg: RunConfig, ctx: ProcessContext) -> str:
    """Remplace les placeholders {nom} d'une chaine de texte par leurs valeurs (case insensitive).
    Si un placeholder n'est pas trouvé, une valeur vide est utilisée avec warning."""

    args = {"timestamp": ctx.timestamp}

    vars_lower = {var.sql_name.lower(): var.value for var in cfg._sql_variables}
    placeholders = set(s for _, s, _, _ in string.Formatter().parse(text) if s and s not in args)
    for p in placeholders:
        if p.lower() not in vars_lower:
            log(f"Placeholder '{p}' non trouvé, utilisation de valeur vide", logging.WARNING)
            args[p] = ""
        else:
            args[p] = vars_lower[p.lower()]

    try:
        return text.format(**args)
    except (KeyError, IndexError, ValueError, TypeError) as e:
        log(f"Erreur format string '{text}': {e}", logging.WARNING)
        return text
