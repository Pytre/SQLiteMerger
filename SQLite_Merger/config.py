import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from constants import DEFAULT_CODEC, INPUT_CODEC, OUTPUT_CODEC
from models import (
    Command,
    Table,
    Variable,
    VariableLevel,
    TableType,
    TableConfig,
    TableConfigAttr,
    VariableConfig,
    VariableConfigAttr,
    CommandConfig,
)
from utils import log


class ConfigSection(Enum):
    """Clés des sections principales du fichier de configuration"""

    BASE = "base"
    SQL_TABLES = "sql_tables"
    SQL_VARIABLES = "sql_variables"
    SQL_COMMANDS = "sql_commands"


class ConfigMapping(Enum):
    """Mapping entre clés JSON et attributs RunConfig pour chargement/sauvegarde config
    Si clé JSON vide alors pas définissable directement dans le fichier de config"""

    # Format : (config section, clé JSON, attribut RunConfig)
    SQLITE_TEMPLATE = (ConfigSection.BASE, "sqlite_template_name", "_sqlite_template_name")
    INPUT_CODEC = (ConfigSection.BASE, "input_codec", "input_codec")
    DISABLE_OUTPUT = (ConfigSection.BASE, "disable_output", "disable_output")
    OUTPUT_CODEC = (ConfigSection.BASE, "output_codec", "output_codec")
    KEEP_DB = (ConfigSection.BASE, "keep_db", "keep_db")
    KEPT_DB_NAME = (ConfigSection.BASE, "kept_db_name", "kept_db_name")
    COPY_CSV_TO_TEMP = (ConfigSection.BASE, "copy_csv_to_temp", "copy_csv_to_temp")
    # Chargement des objets après les chargements de base
    SQL_VARIABLES = (ConfigSection.SQL_VARIABLES, "sql_variables", "_sql_variables")
    SQL_TABLES = (ConfigSection.SQL_TABLES, "sql_tables", "_sql_tables")
    SQL_COMMANDS = (ConfigSection.SQL_COMMANDS, "sql_commands", "_sql_commands")

    def __init__(self, section: ConfigSection, json_key: str, attr_name: str):
        self.section = section
        self.json_key = json_key
        self.attr_name = attr_name


@dataclass
class RunConfig:
    """Configuration d'exécution fournie par l'utilisateur ou l'interface

    Attributes:
        sqlite_template: Fichier template de la base SQLite
        xl_tables_infos: Fichier Excel contenant les tables de configuration
        default_folder: Répertoire source par défaut
        disable_output: True pour désactiver l'export des fichiers (chargé depuis config JSON)
        output_codec: Format d'encodage à utiliser pour les fichiers générés (chargé depuis config JSON)
        keep_db: True pour conserver la base SQLite (chargé depuis config JSON)
        kept_db_name : nom de la base de données récupérées (chargé depuis config JSON)
        copy_csv_to_temp : indique si CSV existants sont copiées dans le dossier temp (chargé depuis config JSON)
        input_codec: Format d'encodage pour les fichiers CSV pré existants (chargé depuis config JSON)
        _sqlite_template_name: Nom par défaut du fichier templace SQLite (chargé depuis config JSON)
        _sql_tables: liste d'objets tables définissant leurs type et correspondance SQLite/Excel/CSV
        _sql_variables: liste d'objets variables définissants leurs attributs
        _sql_commands: liste des commandes à executer pendant le traitement
    """

    # Fichiers/dossiers sources (fournis par utilisateur)
    sqlite_template: Path = None
    xl_tables_infos: Path = None
    default_folder: Path = field(init=False, default=None)
    # Options de comportement (chargée depuis JSON)
    disable_output: bool = False
    output_codec: str = OUTPUT_CODEC
    keep_db: bool = True
    kept_db_name: str = ""
    copy_csv_to_temp: bool = False
    # Config système (chargée depuis JSON)
    input_codec: str = INPUT_CODEC
    _sqlite_template_name: str = ""
    # Config SQLite (chargée depuis JSON)
    _sql_tables: list[Table] = field(default_factory=list)
    _sql_variables: list[Variable] = field(default_factory=list)
    _sql_commands: list[Command] = field(default_factory=list)

    def get_vars(self, levels: list[VariableLevel]) -> list[Variable]:
        """retourne une liste des variables correspondant au levels fournis"""
        return [v for v in self._sql_variables if v.level in levels]

    def get_editable_vars(self) -> list[Variable]:
        """retourne une liste des variables qui peuvent être éditées"""
        uneditable_levels: tuple[VariableLevel] = self._get_uneditable_levels()
        return [v for v in self._sql_variables if v.level not in uneditable_levels]

    def get_uneditable_vars(self) -> list[Variable]:
        """retourne une liste des variables qui ne peuvent pas être éditées"""
        uneditable_levels: tuple[VariableLevel] = self._get_uneditable_levels()
        return [v for v in self._sql_variables if v.level in uneditable_levels]

    @staticmethod
    def _get_uneditable_levels() -> tuple[VariableLevel, ...]:
        """Renvoi les levels de variables ne pouvant être modifiés"""
        return (VariableLevel.INTERNAL,)


@dataclass
class ProcessContext:
    """Configuration de traitement générée dynamiquement durant l'exécution

    Pattern "partiel puis complété" : créée avec valeurs par défaut,
    puis progressivement complétée par populate_temp_dirs().

    Attributes:
        sqlite_db: Chemin de la base SQLite de travail
        timestamp: Timestamp de l'exécution format YYYYMMDD_HHMMSS
        temp_dir: Dossier temporaire
        fact_tables: Liste de tables pour les fichiers à importer depuis un dossier
    """

    sqlite_db: Path = None
    timestamp: str = ""
    temp_dir: Path = None
    fact_tables: list[Table] = field(default_factory=list)


class ConfigLoader:
    def __init__(self, config_file: Path):
        self.config_file: Path = Path(config_file)

    def _load_file(self, file_missing_ok: bool = False) -> dict:
        """Charge et renvoi l'intégralité du fichier JSON"""
        data_dict: dict = {}
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data_dict = json.load(f)
            except json.JSONDecodeError as e:
                log(f"Erreur JSON dans '{self.config_file.name}': {e}", logging.ERROR)
                log(f"Ligne {e.lineno}, colonne {e.colno}", logging.ERROR)
        elif not file_missing_ok:
            log(f"Le fichier de configuration '{self.config_file.name}' n'existe pas", logging.WARNING)
            log("Les données de configuration seront initialisées à vide", logging.WARNING)

        return data_dict

    # ----------------------------------------------
    # Chargement de la config
    # ----------------------------------------------
    def load_config(self, run_cfg: RunConfig) -> bool:
        """Charge la configuration depuis le fichier JSON via ConfigMapping"""
        if not self.config_file:
            log("Fichier à fournir pour chargement de la configuration", logging.INFO)
            return

        data_dict: dict = self._load_file()

        for cfg_map in ConfigMapping:
            if not hasattr(run_cfg, cfg_map.attr_name):
                log(f"L'attribut '{cfg_map.attr_name}' n'existe pas dans RunConfig !", logging.WARNING)
                continue
            if not cfg_map.json_key:
                continue

            # récupération valeur du json dict
            attr_val = self._load_get_value(data_dict, cfg_map)
            if not attr_val:
                continue

            # Transformation valeur en objet
            try:
                attr_val = self._load_transform(cfg_map, run_cfg, attr_val)
            except Exception as e:
                log(f"Erreur transformation '{cfg_map.section.value}' : {e}", logging.ERROR)

            # Affectation valeur à RunConfig
            setattr(run_cfg, cfg_map.attr_name, attr_val)

        return True

    def _load_get_value(self, data_dict: dict, cfg_map: ConfigMapping) -> Any:
        """retourne la valeur à utiliser en fonction de la section"""
        if cfg_map.section is ConfigSection.BASE:
            section: dict = data_dict.get(cfg_map.section.value, None)
            attr_val = section.get(cfg_map.json_key, None) if isinstance(section, dict) else None
        else:
            attr_val: dict | list = data_dict.get(cfg_map.json_key, None)

        # alerter si nécessaire quand aucune valeur dans le fichier de config
        none_allowed: tuple[str] = (ConfigMapping.INPUT_CODEC.json_key, ConfigMapping.OUTPUT_CODEC.json_key)
        if attr_val is None:
            if cfg_map.json_key not in none_allowed:
                log(f"Pas de valeurs dans fichier de config pour '{cfg_map.attr_name}'", logging.WARNING)
                return None

        return attr_val

    # ----------------------------------------------
    # Transformation valeurs string chargées
    # ----------------------------------------------
    def _load_transform(self, cfg_map: ConfigMapping, run_cfg: RunConfig, attr_val: Any) -> Any:
        """Transformation d'éléments du fichier de config en objet"""
        if cfg_map.section is ConfigSection.SQL_TABLES:
            return self._load_tables(run_cfg, attr_val)
        elif cfg_map.section is ConfigSection.SQL_VARIABLES:
            return self._load_variables(attr_val)
        elif cfg_map.section is ConfigSection.SQL_COMMANDS:
            return self._load_commands(attr_val)

        return attr_val

    @staticmethod
    def _load_tables(cfg: RunConfig, list_of_dicts: list[dict]) -> list[Table]:
        """Transforme une liste de dict en liste de tables"""
        tables: list[Table] = []
        for data_dict in list_of_dicts:
            tbl_id = data_dict.get(TableConfigAttr.ID.value, data_dict)

            # initialisation codec si manquant
            codec_key = TableConfigAttr.CSV_ENCODING.value
            if codec_key not in data_dict:
                if data_dict.get(TableConfigAttr.TYPE.value, "") is TableType.OUTPUT:
                    data_dict[codec_key] = cfg.output_codec if cfg.output_codec else OUTPUT_CODEC
                elif data_dict.get(TableConfigAttr.EXCEL_NAME.value, ""):
                    data_dict[codec_key] = DEFAULT_CODEC
                else:
                    data_dict[codec_key] = cfg.input_codec if cfg.input_codec else INPUT_CODEC

            try:
                tbl_cfg: TableConfig = Table.dict_to_config(data_dict)
                table: Table = Table(tbl_cfg)
                tables.append(table)
            except Exception as e:
                log(f"Echec conversion '{tbl_id}' en objet Table : {e}", logging.CRITICAL)
                log("Echec initialisation config. Corriger et relancer l'application.", logging.CRITICAL)

        return tables

    @staticmethod
    def _load_variables(list_of_dicts: list[dict]) -> list[Variable]:
        """Transforme une liste de dict en liste de variables"""
        variables: list[Variable] = []
        for dict_val in list_of_dicts:
            var_id = dict_val.get(VariableConfigAttr.SQL_NAME, dict_val)
            try:
                var_cfg: VariableConfig = Variable.dict_to_config(dict_val)
                var = Variable(var_cfg)
                if not var.value_is_valid(empty_is_ok=True):
                    log(
                        f"La valeur par défaut pour '{var.sql_name}' ne respecte pas "
                        + f"le regex de contrôle '{var.regex_ctrl}'",
                        logging.WARNING,
                    )
                variables.append(var)
            except Exception as e:
                log(f"Echec conversion '{var_id}' en objet Variable : {e}", logging.CRITICAL)
                log("Echec initialisation config. Corriger et relancer l'application.", logging.CRITICAL)
                return []

        return variables

    @staticmethod
    def _load_commands(list_of_dicts: list[dict]) -> list[Command]:
        """Transforme une liste de dict en liste de commandes"""
        commandes: list[Command] = []
        for dict_val in list_of_dicts:
            try:
                cmd_cfg: CommandConfig = Command.dict_to_config(dict_val)
                cmd = Command(cmd_cfg)
                commandes.append(cmd)
            except Exception as e:
                log(f"Echec conversion '{dict_val}' en objet Commande : {e}", logging.CRITICAL)
                log("Echec initialisation config. Corriger et relancer l'application.", logging.CRITICAL)
                return []

        return commandes

    # ----------------------------------------------
    # Sauvegarde de la config
    # ----------------------------------------------
    def save_run_config(self, cfg: RunConfig) -> bool:
        """Sauvegarde la configuration dans le fichier JSON via ConfigMapping"""
        # TODO : pas encore utilisé - à intégrer éventuellement avec gestion variables ?

        default_dict: dict = {
            "_help_0": "-------------------------------------------------------------------",
            "_help_1": "Attention le backslash est le caractère d'échappement pour les json",
            "_help_2": "-------------------------------------------------------------------",
        }

        full_dict: dict = self._load_file(file_missing_ok=True)
        if not full_dict:
            full_dict = default_dict

        run_subdict: dict = {}

        for mapping in ConfigMapping:
            if not mapping.json_key or mapping.section is not ConfigSection.BASE:
                continue

            if not hasattr(cfg, mapping.attr_name):
                log(f"Config_dict : l'attribut '{mapping.attr_name}' n'existe pas !", logging.WARNING)
                continue
            run_subdict[mapping.json_key] = getattr(cfg, mapping.attr_name)

        full_dict[ConfigSection.BASE.value] = run_subdict

        try:
            with open(self.config_file, mode="w", encoding="utf-8") as f:
                json.dump(full_dict, f, indent=2, ensure_ascii=False)
        except (OSError, PermissionError) as e:
            log(f"Erreur lors de la sauvegarde du fichier de config : {e}", logging.ERROR)
            return False

        return True
