import logging
import os
import re
import shutil
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from threading import Event

from config import RunConfig, ProcessContext, ConfigLoader
from excel_converter import ExcelConverter
from models import Table, TableConfig, VariableLevel, Variable, expand_vars
from sqlite_processor import SQLiteProcessor
from utils import UserInterruptedError, log, get_exec_dir, parse_arguments


class SQLiteMerger:
    """Classe principale pour gérer la fusion de balances dans SQLite"""

    def __init__(self, config_file: str = "", template_file: str = "", xl_file: str = ""):
        self.config_file: Path = Path(config_file) if config_file else get_exec_dir() / "SQLite_Merger.cfg"
        self.default_template: Path = Path(template_file) if template_file else None
        self.default_xl: Path = Path(xl_file) if xl_file else None

        self.stop_event: Event = Event()

        self.cfg: RunConfig = RunConfig()
        self.ctx: ProcessContext = ProcessContext()
        self.config_loader: ConfigLoader = ConfigLoader(self.config_file)

        self.excel_converter: ExcelConverter = ExcelConverter()
        self.sqlite_operations: SQLiteProcessor = SQLiteProcessor()

        self.load_config()
        self.init_defaults()

    # ----------------------------------------------
    # Récupération infos de transformation
    # ----------------------------------------------
    def init_defaults(self):
        """Initialise les valeurs par défaut au démarrage"""
        try:
            self.cfg.default_folder = Path().cwd()
            self.set_sqlite_template(use_default=True)
            self.set_xl_tables_infos(first=True)
        except Exception as e:
            log(traceback.format_exc(), logging.CRITICAL)
            log(f"Problème d'initialisation des valeurs par défaut : {e}", logging.CRITICAL)

    def set_variables(self):
        """Demander à l'utilisateur de définir les variables à utiliser"""

        def user_input(vars: list[Variable]):
            for v in vars:
                while True:
                    v.value = input(f"{v.sql_name} : ").strip()
                    if v.value_is_valid():
                        break
                    log(f"Format invalide (regex de ctrl : '{v.regex_ctrl}')", logging.WARNING)
                    if input("Voulez vous tout de même valider la valeur ? (y/N)").strip().lower() == "y":
                        break

        user_input([v for v in self.cfg._sql_variables if v.level is VariableLevel.USER])
        if input("Voulez vous saisir les variables avancées ? (y/N)").strip().lower() == "y":
            user_input([v for v in self.cfg._sql_variables if v.level is VariableLevel.ADVANCED])

    def set_sqlite_template(self, use_default: bool = False):
        """Recherche le template pour la base SQLite"""
        if self.default_template is None:
            self.default_template = get_exec_dir() / self.cfg._sqlite_template_name

        if self.default_template.exists() and self.default_template.is_file():
            self.cfg.sqlite_template = self.default_template

        if use_default:
            return

        log("Recherche fichier template SQLite...")

        try:
            pattern = re.compile(r"^.*\.sqlite$", re.IGNORECASE)
            self.cfg.sqlite_template = self._file_selection(get_exec_dir(), pattern, first=use_default)
        except FileNotFoundError:
            raise FileNotFoundError("Aucun fichier trouvé pour le template SQLite !")

        log(f"Fichier template SQLite : {self.cfg.sqlite_template.name}")

    def set_xl_tables_infos(self, first: bool = False):
        """Recherche le fichier Excel avec les infos des tables"""
        if self.default_xl and self.default_xl.exists():
            self.cfg.xl_tables_infos = self.default_xl
            return

        if not first:
            log("Recherche fichier Tables_Infos...")

        try:
            pattern = re.compile(r"^SQLite_Merger_Tables_Infos.*\.xlsx$", re.IGNORECASE)
            self.cfg.xl_tables_infos = self._file_selection(self.cfg.default_folder, pattern, first=first)
        except FileNotFoundError:
            raise FileNotFoundError("Aucun fichier trouvé pour Tables_Infos !")

        if not first:
            log(f"Fichier Tables_Infos : {self.cfg.xl_tables_infos.name}")

    def _file_selection(self, folder: Path, pattern: re.Pattern, first: bool = False) -> Path:
        """Sélection d'un fichier correspondant au pattern.
        Si first == True alors retourne le premier fichier trouvé."""
        files: list[Path] = []

        for file in folder.iterdir():
            if file.is_file() and pattern.match(file.name):
                files.append(file)

        # Init auto avec premier fichier trouvé ou None si demandé, pas d'erreur levée
        if first:
            return files[0] if files else None

        # Si aucun fichier ne correspond, erreur renvoi None
        if not files:
            raise FileNotFoundError("Aucun fichier trouvé !")

        # Si un seul fichier alors utilisation directe
        if len(files) == 1:
            return files[0]

        # Si plusieurs fichiers trouvés
        log("Plusieurs fichiers trouvés :")
        log(f"  {1}. {files[0].name} (choix par défaut)")
        for i, f in enumerate(files[1:], 2):
            log(f"  {i}. {f.name}")
        while True:
            choice = input("Numéro du fichier à utiliser ou valider pour fichier par défaut : ").strip()

            idx = int(choice) - 1 if choice.isdigit() else 0 if choice == "" else -1
            if idx < 0 or idx >= len(files):
                log("Choix invalide, réessayez.", logging.WARNING)
                continue

            break

        return files[idx]

    # ----------------------------------------------
    # Chargement / sauvegarde config générale
    # ----------------------------------------------
    def load_config(self) -> bool:
        """Charge la configuration depuis le fichier JSON via ConfigMapping"""
        return self.config_loader.load_config(self.cfg)

    def save_run_config(self) -> bool:
        """Sauvegarde la configuration dans le fichier JSON via ConfigMapping"""
        return self.config_loader.save_run_config(self.cfg)

    # ----------------------------------------------
    # Dossiers temporaires, création / alim
    # ----------------------------------------------
    def prepare_temp_workspace(self):
        """Crée les dossiers nécessaires et alimente les dossiers temporaires"""

        log("Créations dossiers temporaires...", start_timer=True)
        temp_base: Path = Path(tempfile.gettempdir()) / f"SQLite_{self.ctx.timestamp}"
        temp_base.mkdir(parents=True, exist_ok=True)
        self.ctx.temp_dir = temp_base

        os.chdir(self.cfg.default_folder)  # change working directory to default folder

        self._reset_tables()
        self._create_database()
        self._tables_from_excel()
        self._tables_from_csv_source()

    def _reset_tables(self):
        """Remet à 0 les tables et chemins initialisés d'une execution précédente"""

        # Reset des chemins d'imports
        for tbl in self.cfg._sql_tables:
            tbl.import_filepath = None

        # Reset des tables identifiées dans les dossiers
        self.ctx.fact_tables = []

    def _create_database(self):
        """Création base SQLite à partir du template"""
        if self.cfg.kept_db_name:
            filename = expand_vars(self.cfg.kept_db_name, self.cfg, self.ctx)
        else:
            filename = f"Database_{self.ctx.timestamp}.sqlite"

        self.ctx.sqlite_db = self.ctx.temp_dir / filename

        log("Copie du template SQLite dans dossier temporaire", start_timer=True)
        shutil.copy(self.cfg.sqlite_template, self.ctx.sqlite_db)

    def _tables_from_excel(self):
        """Crée les fichiers CSV temporaires à partir du fichier Excel et renvoi un dict des fichiers créés"""
        temp_dir: Path = self.ctx.temp_dir

        tbl_from_excel = [tbl for tbl in self.cfg._sql_tables if tbl.from_excel]
        if not tbl_from_excel:
            return

        log("Création des fichiers CSV temporaires à partir de Tables_Infos...", start_timer=True)
        tables_mapping: dict[str, tuple[Path, str]] = {}
        for tbl in tbl_from_excel:
            tbl.import_filepath = temp_dir / tbl.csv_name
            tables_mapping[tbl.excel_name] = tbl.import_filepath, tbl.csv_encoding

        self.excel_converter.tables_to_csv(self.cfg.xl_tables_infos, tables_mapping)

    def _tables_from_csv_source(self):
        """Identifie les tables à importer avec csv_source (fichiers et dossiers)"""
        tbl_with_source = [tbl for tbl in self.cfg._sql_tables if tbl.from_csv_source]
        if not tbl_with_source:
            return

        if self.cfg.copy_csv_to_temp:
            log("Identification et copie fichiers et dossiers à importer...", start_timer=True)
        else:
            log("Identification fichiers et dossiers à importer...", start_timer=True)

        # lister les fichiers et dossiers à utiliser
        from_files: list[tuple[Table, Path]] = []
        from_folders: list[tuple[Table, Path]] = []
        for src_tbl in tbl_with_source:
            resolved_source = Path(expand_vars(str(src_tbl.csv_source), self.cfg, self.ctx))
            if not resolved_source.exists():
                if not src_tbl.csv_missing_ok:
                    log(f"Source introuvable : {resolved_source}", logging.WARNING)
            elif resolved_source.is_file():
                from_files.append((src_tbl, resolved_source))
            elif resolved_source.is_dir():
                from_folders.append((src_tbl, resolved_source))

        # Récup fichiers et dossiers sources et initialisation de leurs emplacements
        self._tables_from_files(from_files)
        self._tables_from_folders(from_folders)

    def _tables_from_files(self, from_files: list[tuple[Table, Path]]):
        """Identifie les tables à importer pour csv pré existants"""
        if from_files and self.cfg.copy_csv_to_temp:
            dest_folder: Path = self.ctx.temp_dir / "000_CSV"
            dest_folder.mkdir(parents=True, exist_ok=True)

        for file_num, (src_tbl, file_path) in enumerate(from_files, start=1):
            # Si dossier temporaire copie fichier source
            if self.cfg.copy_csv_to_temp:
                dest_file: Path = dest_folder / f"{file_num:03d}_{file_path.name}"
                shutil.copy(file_path, dest_file)
                src_tbl.import_filepath = dest_file
            else:
                src_tbl.import_filepath = file_path

    def _tables_from_folders(self, from_folders: list[tuple[Table, Path]]):
        """Identifie les tables à importer pour une table multi csv"""
        for folder_num, (src_tbl, folder_path) in enumerate(from_folders, start=1):
            # Si dossier temporaire copie dossier source
            if self.cfg.copy_csv_to_temp:
                dest_folder: Path = self.ctx.temp_dir / f"{folder_num:03d}_{folder_path.name}"
                dest_folder.mkdir(parents=True, exist_ok=True)
                shutil.copytree(folder_path, dest_folder, dirs_exist_ok=True)
            else:
                dest_folder: Path = folder_path

            # Création TableConfig pour tables du dossier
            tables: list[Table] = []
            tbl_cfg: TableConfig = src_tbl.get_cfg()
            tbl_cfg.CSV_SOURCE = None

            # Création tables correspondant aux fichiers csv à importer
            for file in dest_folder.rglob("*"):
                if not file.is_file() or not src_tbl.csv_pattern_regex.search(file.name):
                    continue

                table: Table = Table(tbl_cfg)
                table.import_filepath = file

                tables.append(table)

            # Ajout des tables créées à liste des tables du ProcessContext
            if tables:
                tables.sort(key=lambda tbl: tbl.import_filepath.name)
                self.ctx.fact_tables.extend(tables)

    # ----------------------------------------------
    # Orchestration
    # ----------------------------------------------
    def run(self, cfg: RunConfig = None):
        """Fonction principale"""
        separator: str = "=" * 70
        timer_start: datetime = datetime.now()
        success: bool = False
        self.stop_event.clear()

        # Récupération de la config
        if cfg:
            self.cfg = cfg
        else:
            try:
                log(separator)
                log("SQLite Merger")
                log(separator)
                self._run_ask_user()  # si pas de config demander à l'utilisateur les infos
            except UserInterruptedError:
                return False
            except Exception as e:
                log(traceback.format_exc())
                log(f"Problème initialisation : {e}", logging.CRITICAL)
                return False

        # Executer les taches et renvoyer le résultat
        try:
            success = self._run_execute()
        except UserInterruptedError:
            return False
        except Exception as e:
            log(traceback.format_exc())
            log(f"Problème execution : {e}", logging.CRITICAL)
            return False
        finally:
            # Nettoyage des fichiers temporaires si ils ont été créés
            if self.ctx.temp_dir and self.ctx.temp_dir.exists():
                log("Nettoyage des fichiers temporaires...")
                shutil.rmtree(self.ctx.temp_dir, ignore_errors=True)

        # Message de fin
        elapsed_time = (datetime.now() - timer_start).total_seconds()
        elapsed_str = f"{int(elapsed_time) // 60:02d}:{int(elapsed_time) % 60:02d}"
        log(separator)
        log(f"Exécution terminée avec succès (durée : {elapsed_str})")
        log(separator)

        return success

    def _run_ask_user(self):
        # Demander à l'utilisateur les infos nécessaire pour lancer la tâche
        self.set_variables()
        self.set_sqlite_template()
        self.set_xl_tables_infos()

        # Controle de l'existence des fichiers (même si peu de risque qu'ils soient supprimés entre temps)
        files: dict[str, Path] = {
            "SQLite template": self.cfg.sqlite_template,
            "Tables infos": self.cfg.xl_tables_infos,
        }
        for label, file in files.items():
            if not file.exists():
                raise FileNotFoundError(f"{label} ('{file.name}') n'existe pas !!!")

    def _run_execute(self) -> bool:
        self.ctx.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log(f"Timestamp : {self.ctx.timestamp}")

        # Création des dossiers temporaires et identification des fichiers à importer
        self.prepare_temp_workspace()
        log("", stop_timer=True)

        # Exécution des opérations SQLite et récupération des fichiers de sortie
        self.sqlite_operations.start_all(self.cfg, self.ctx, self.stop_event)
        log("", stop_timer=True)

        return True


def main():
    """Point d'entrée du programme"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_arguments()  # Parser les arguments ligne de commande
    success: bool = False
    merger = SQLiteMerger(args.config, args.template, args.infos)

    try:
        success = merger.run()
    except (KeyboardInterrupt, UserInterruptedError):
        print("\n\nInterruption par l'utilisateur.")
        sys.exit(130)
    finally:
        input("Appuyez sur une touche pour quitter...")
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
