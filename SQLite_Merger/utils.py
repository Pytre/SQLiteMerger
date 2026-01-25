import argparse
import codecs
import logging
import sys
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from constants import LOGGER_NAME


class UserInterruptedError(Exception):
    """Exception levée lors d'une demande d'arrêt par l'utilisateur"""

    pass


class TimerAction(Enum):
    """Actions timer pour le logging"""

    START = auto()
    STOP = auto()


def log(msg: str, log_level: int = logging.INFO, start_timer: bool = False, stop_timer: bool = False):
    """Log les messages en utilisant un Logger"""
    if msg:
        logger: logging.Logger = logging.getLogger(LOGGER_NAME)
        logger.log(log_level, msg)
    if start_timer or stop_timer:
        timer(stop=stop_timer)


def timer(wait_in_sec: int = 5, stop: bool = False):
    """Démarre/Stop le timer si utilisation GUI sinon ne fait rien. Relancer le timer le réinitialise"""
    logger: logging.Logger = logging.getLogger(LOGGER_NAME)
    if stop:
        logger.info("", extra={"action": TimerAction.STOP})
    else:
        logger.info("", extra={"action": TimerAction.START, "start_time": datetime.now(), "wait_in_sec": wait_in_sec})


def get_valid_encoding(encoding: str, fallback: str = "", warn: bool = True) -> str | None:
    """Renvoi l'encoding (ou son fallback si fourni) si valide. Sinon renvoi None."""
    if encoding is None:
        raise ValueError("Encoding doit être une string pas None")
    try:
        codecs.lookup(encoding)
        return encoding
    except LookupError:
        if warn:
            log(f"Format d'encoding non reconnu : '{encoding}'", logging.WARNING)

    return None if not fallback else get_valid_encoding(fallback)


def get_exec_dir() -> Path:
    """Retourne le répertoire de l'exécutable ou du script"""
    if getattr(sys, "frozen", False):
        # PyInstaller : dossier de l'exe
        return Path(sys.executable).parent
    else:
        # Sinon : dossier du script
        return Path(__file__).parent


def parse_arguments() -> argparse.Namespace:
    """Parse les arguments de ligne de commande"""
    parser = argparse.ArgumentParser(
        description="SQLite Merger - Fusion et transformation de Balances",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  SQLite_Merge.exe
  SQLite_Merge.exe --config /path/to/custom_config.cfg
  SQLite_Merge.exe -c ./my_config.cfg
        """,
    )

    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default="",
        metavar="PATH",
        help="Chemin vers le fichier de configuration (défaut: SQLite_Merger.cfg du dossier de l'executable)",
    )

    parser.add_argument(
        "-t",
        "--template",
        type=str,
        default="",
        metavar="PATH",
        help="Chemin vers la base template SQLite (défaut: SQLite_Merger_DB_Template.sqlite du dossier de l'executable)",
    )

    parser.add_argument(
        "-i",
        "--infos",
        type=str,
        default="",
        metavar="PATH",
        help="Chemin vers le fichier excel des infos (défaut: premier fichier qui matche SQLite_Merger_Tables_Infos dans dossier de l'executable)",
    )

    return parser.parse_args()
