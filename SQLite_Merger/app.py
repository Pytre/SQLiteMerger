import logging
import traceback
import ttkbootstrap as ttk
import ttkbootstrap.constants as cst
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, Widget, TclError, Event as TkEvent
from typing import Callable

from about_window import AboutWindow
from config import RunConfig
from constants import LOGGER_NAME
from merger import SQLiteMerger
from models import Variable, VariableLevel
from utils import UserInterruptedError, TimerAction, parse_arguments, log


APP_NAME = "SQLite Merger"
NO_FOLDER_SELECTED = "Aucun dossier sélectionné"
NO_FILE_SELECTED = "Aucun fichier sélectionné"


class App(ttk.Window):
    def __init__(self, config_file: str = "", template_file: str = "", xl_file: str = ""):
        super().__init__(themename="darkly", iconphoto=None)  # Thèmes: darkly, lumen, flatly, litera, minty, etc.
        # super().__init__(themename="lumen")  # Thèmes: cosmo, darkly, flatly, litera, minty, etc.

        LogHandler(self)  # initialisation logging handler
        self.logger: logging.Logger = logging.getLogger(LOGGER_NAME)

        self.processing: bool = False
        self.processing_thread: threading.Thread = None
        self.is_stopping: bool = False
        self._timer_after_id: str = None

        self.folder_var: ttk.StringVar = ttk.StringVar()
        self.template_var: ttk.StringVar = ttk.StringVar()
        self.excel_var: ttk.StringVar = ttk.StringVar()
        self.confirm_var: ttk.BooleanVar = ttk.BooleanVar(value=True)

        self.merger: SQLiteMerger = SQLiteMerger(config_file=config_file, template_file=template_file, xl_file=xl_file)
        self.user_vars: list[Variable] = []
        self.advanced_vars: list[Variable] = []

        self.app_title: str = APP_NAME + (f" - {self.merger.config_file}" if self.merger.config_file else "")

        # Load config
        self.set_config_vars()
        self.set_default_files()

        # UI setup
        self.setup_app_identity()
        self.setup_ui()
        self.setup_binds_and_traces()

    # ----------------------------------------------
    # Chargement config
    # ----------------------------------------------
    def _load_config(self, filepath: Path | None = None):
        """charger la configuration si filepath (sinon recharge)"""
        # Recharger la config
        if filepath:
            self.merger.config_file = Path(filepath)
            self.merger.load_config()
            self.app_title: str = APP_NAME + f" - {self.merger.config_file}"

        # Mettre à jour l'UI avec les nouvelles valeurs
        self.title(self.app_title)
        self.set_config_vars()
        self.set_default_files()

        log(f"Configuration chargée : {Path(filepath).name}", logging.INFO)

    def set_config_vars(self):
        """Initialiser les listes de variables à partir de la config"""
        self.user_vars: list[Variable] = self.merger.cfg.get_vars([VariableLevel.USER])
        self.advanced_vars: list[Variable] = self.merger.cfg.get_vars([VariableLevel.ADVANCED])

    def set_default_files(self):
        """Initialise les champs des fichiers à utiliser par leurs valeurs défaut"""

        # list de tuples avec attribut source dans self.merger.run_cfg et attribut destination dans self
        mapping = [
            ("default_folder", "folder_var"),
            ("sqlite_template", "template_var"),
            ("xl_tables_infos", "excel_var"),
        ]

        cfg: RunConfig = self.merger.cfg
        for src_attr, dest_attr in mapping:
            if not hasattr(cfg, src_attr):
                log(f"Initialisation attribut inconnu : merger.{src_attr}", logging.ERROR)
                continue
            if not hasattr(self, dest_attr):
                log(f"Initialisation attribut inconnu : {dest_attr}", logging.ERROR)
                continue

            dest_var: ttk.StringVar = getattr(self, dest_attr)
            if not isinstance(dest_var, ttk.StringVar):
                log(f"Initialisation attribut '{dest_attr}' n'est pas de type StringVar", logging.ERROR)
                continue

            value = getattr(cfg, src_attr)
            default_msg = NO_FILE_SELECTED if dest_var is not self.folder_var else NO_FOLDER_SELECTED
            default_value = Path(value) if value else default_msg

            dest_var.set(value=default_value)

    # ----------------------------------------------
    # Création UI
    # ----------------------------------------------
    def setup_app_identity(self):
        self.title(self.app_title)

        try:
            icon_path = Path(__file__).parent / "res/app_icon.png"
            self.icon_img = ttk.PhotoImage(file=str(icon_path))
            self.iconphoto(True, self.icon_img)
        except Exception:
            pass  # Ignorer si l'icône ne peut pas être chargée

    def setup_ui(self):
        self.geometry("800x600")

        main_frame = ttk.Frame(self, padding=15)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(6, weight=1)  # Pour que la textbox s'étende verticalement

        self.menu_frame = ttk.Frame(self, bootstyle=cst.PRIMARY)

        self.menu_frame.pack(fill=cst.X)
        main_frame.pack(fill=cst.BOTH, expand=cst.YES)

        self._setup_menu(self.menu_frame)
        self._setup_ui_files_selection(main_frame)
        self._setup_ui_toggles(main_frame)
        self._setup_ui_separator(main_frame)
        self._setup_ui_textbox(main_frame)
        self._setup_ui_bottom_buttons(main_frame)

    def _setup_menu(self, menu_frame: ttk.Frame):
        """Configure la barre de menu de l'application"""
        # Style
        style = self.style
        style.configure("NoArrow.TMenubutton", arrowsize=0, arrowpadding=0, arrowcolor="transparent")

        # Création des Menubutton
        file_mb = ttk.Menubutton(menu_frame, text="Fichier", style="NoArrow.TMenubutton", bootstyle=cst.PRIMARY)
        file_mb.pack(side=cst.LEFT)
        about_mb = ttk.Menubutton(menu_frame, text="?", style="NoArrow.TMenubutton", bootstyle=cst.PRIMARY)
        about_mb.pack(side=cst.LEFT)

        # Création du menu déroulant attaché au bouton
        file_menu = ttk.Menu(file_mb, tearoff=0)
        file_menu.add_command(label="Charger configuration...", command=self.load_config_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.on_closing)
        file_mb["menu"] = file_menu

        # Création du menu déroulant à propos
        about_menu = ttk.Menu(about_mb, tearoff=0)
        about_menu.add_command(label="À propos...", command=self.open_about)
        about_mb["menu"] = about_menu

    def _setup_ui_files_selection(self, main_frame: ttk.Frame):
        # Folder source with files to import
        folder_label = ttk.Label(main_frame, text="Dossier source :")
        self.folder_entry = ttk.Entry(main_frame, textvariable=self.folder_var)
        folder_button = ttk.Button(main_frame, text="...", command=self.select_folder, width=2, padding=(5, 2))
        folder_button.configure(bootstyle=cst.PRIMARY)

        # SQLite template file
        temp_label = ttk.Label(main_frame, text="Template Database :")
        self.template_entry = ttk.Entry(main_frame, textvariable=self.template_var)
        temp_button = ttk.Button(main_frame, text="...", command=self.select_template_file, width=2, padding=(5, 2))
        temp_button.configure(bootstyle=cst.PRIMARY)

        # Excel infos file
        xl_label = ttk.Label(main_frame, text="Fichier Excel :")
        self.excel_entry = ttk.Entry(main_frame, textvariable=self.excel_var)
        xl_button = ttk.Button(main_frame, text="...", command=self.select_excel_file, width=2, padding=(5, 2))
        xl_button.configure(bootstyle=cst.PRIMARY)

        # Placement des widgets
        folder_label.grid(row=0, column=0, sticky=cst.W, padx=(0, 10), pady=(0, 10))
        self.folder_entry.grid(row=0, column=1, sticky=cst.EW, padx=(0, 10), pady=(0, 10))
        folder_button.grid(row=0, column=2, pady=(0, 10))

        temp_label.grid(row=1, column=0, sticky=cst.W, padx=(0, 10), pady=(0, 10))
        self.template_entry.grid(row=1, column=1, sticky=cst.EW, padx=(0, 10), pady=(0, 10))
        temp_button.grid(row=1, column=2, pady=(0, 10))

        xl_label.grid(row=2, column=0, sticky=cst.W, padx=(0, 10), pady=(0, 10))
        self.excel_entry.grid(row=2, column=1, sticky=cst.EW, padx=(0, 10), pady=(0, 10))
        xl_button.grid(row=2, column=2, pady=(0, 10))

    def _setup_ui_toggles(self, main_frame: ttk.Frame):
        frame = ttk.Frame(main_frame)
        frame.grid(row=3, column=0, columnspan=3, sticky=cst.NSEW, pady=(5, 5))

        label = ttk.Label(frame, text="Confirmation des variables")
        self.confirm_cb = ttk.Checkbutton(frame, text="", variable=self.confirm_var)
        self.confirm_cb.configure(bootstyle="primary-round_toggle")

        label.pack(side=cst.LEFT, anchor=cst.CENTER)
        self.confirm_cb.pack(side=cst.LEFT, anchor=cst.CENTER, padx=(10, 0), pady=(4, 0))

    def _setup_ui_separator(self, main_frame: ttk.Frame):
        separator = ttk.Separator(main_frame, orient=cst.HORIZONTAL)
        separator.grid(row=4, column=0, columnspan=3, sticky=cst.EW, pady=10)

    def _setup_ui_textbox(self, main_frame: ttk.Frame):
        header_label = ttk.Label(main_frame, text="Output :", font=("Helvetica", 10, "bold"))
        header_label.grid(row=5, column=0, columnspan=3, sticky=cst.W, pady=(0, 5))

        # Sous frame pour le textbox avec scrollbar
        text_frame = ttk.Frame(main_frame)
        text_frame.grid(row=6, column=0, columnspan=3, sticky=cst.NSEW, pady=(0, 10))

        # Placement dans la sous frame des contrôles
        scrollbar = ttk.Scrollbar(text_frame)
        self.output_text = ttk.Text(text_frame, wrap=cst.WORD, state=cst.DISABLED, height=15)

        self.output_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.output_text.yview)

        scrollbar.pack(side=cst.RIGHT, fill=cst.Y)
        self.output_text.pack(side=cst.LEFT, fill=cst.BOTH, expand=cst.YES)

        # Menu contextuel de la textbox
        self._context_menu_for_textbox()

    def _context_menu_for_textbox(self):
        """Configure le menu contextuel (clic droit) pour la textbox"""
        self.context_menu = ttk.Menu(self.output_text, tearoff=0)
        self.context_menu.add_command(label="Copier", command=self.copy_selection)
        self.context_menu.add_command(label="Tout sélectionner", command=self.select_all)

        self.output_text.bind("<Button-3>", self.display_context_menu)

    def _setup_ui_bottom_buttons(self, main_frame: ttk.Frame):
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=7, column=0, columnspan=3, sticky=cst.EW)

        # Ajout bouton pour accèder aux settings supplémentaires
        advanced_button = ttk.Button(button_frame, text="Variables", command=self.open_vars_dialog, width=15)
        advanced_button.configure(bootstyle=cst.SECONDARY)
        advanced_button.pack(side=cst.LEFT, anchor=cst.CENTER)

        # Boutons démarrer / quitter
        self.quit_button = ttk.Button(button_frame, text="Quitter", command=self.quit, width=15)
        self.quit_button.configure(bootstyle=cst.DANGER)

        self.run_button = ttk.Button(button_frame, text="Démarrer", command=self.start_stop_toggle, width=15)
        self.run_button.configure(bootstyle=cst.PRIMARY)

        self.quit_button.pack(side=cst.RIGHT)
        self.run_button.pack(side=cst.RIGHT, padx=(0, 10))

    # ----------------------------------------------
    # Définition des binds et des traces
    # ----------------------------------------------
    def setup_binds_and_traces(self):
        # Ordre personnalisé pour Tab
        for widget in self._get_focus_order():
            widget.bind("<Tab>", self._focus_next)
            widget.bind("<Shift-Tab>", self._focus_next)
            widget.bind("<ISO_Left_Tab>", self._focus_next)  # pour Linux

        # Raccourci clavier pour la textbox de sortie du texte
        self.output_text.bind("<Control-c>", lambda _: self.copy_selection())
        self.output_text.bind("<Control-a>", lambda _: self.select_all())

        # Fermeture de l'application
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _get_focus_order(self) -> tuple[Widget, ...]:
        if not hasattr(self, "_focus_order"):
            self._focus_order = (self.run_button, self.quit_button)

        return self._focus_order

    def _focus_next(self, event: TkEvent):
        """Donne le focus au widget spécifié"""
        focus_order: tuple[Widget, ...] = self._get_focus_order()

        offset: int = 1
        if event.state & 0x1:  # si touche shift pressée
            offset = -1

        curr_pos = focus_order.index(event.widget)
        new_pos = (curr_pos + offset) % len(focus_order)

        focus_order[new_pos].focus_set()
        return "break"  # Empêche le comportement par défaut de Tab

    # ----------------------------------------------
    # Interaction UI
    # ----------------------------------------------
    def load_config_dialog(self):
        """Charge un nouveau fichier de configuration"""
        filepath = filedialog.askopenfilename(
            title="Sélectionner un fichier de configuration",
            filetypes=[("Fichiers config", "*.cfg"), ("Fichiers JSON", "*.json"), ("Tous les fichiers", "*.*")],
            initialdir=self.merger.config_file.parent,
        )

        if not filepath:
            return

        self._load_config(filepath)

    def display_context_menu(self, event: TkEvent):
        """Affiche le menu contextuel à la position du clic"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def copy_selection(self):
        """Copie le texte sélectionné dans le presse-papier"""
        try:
            text = self.output_text.get(cst.SEL_FIRST, cst.SEL_LAST)
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass  # Pas de sélection

    def select_all(self):
        """Sélectionne tout le texte"""
        self.output_text.tag_add(cst.SEL, "1.0", cst.END)
        self.output_text.mark_set(cst.INSERT, "1.0")
        self.output_text.see(cst.INSERT)
        return "break"

    def on_folder_click(self):
        """Gère le clic sur le champ template (ne fait rien si traitement en cours)"""
        if not self.processing:
            self.select_folder()

    def on_template_click(self):
        """Gère le clic sur le champ template (ne fait rien si traitement en cours)"""
        if not self.processing:
            self.select_template_file()

    def on_excel_click(self):
        """Gère le clic sur le champ Excel (ne fait rien si traitement en cours)"""
        if not self.processing:
            self.select_excel_file()

    # ----------------------------------------------
    # Lock / Unlock UI
    # ----------------------------------------------
    def start_stop_toggle(self):
        """Bascule entre démarrer et arrêter le traitement"""
        if self.processing:
            self.stop_task(kill=True)
            return

        # montrer fenêtre des variables si variables éditables existent
        if self.editable_vars_exist() and self.confirm_var.get():
            self.open_vars_dialog(start_after=True)
        else:
            self.start_task()

    def toggle_controls(self, enable: cst):
        """Active ou désactive tous les contrôles sauf le bouton d'arrêt"""
        state = cst.NORMAL if enable else cst.DISABLED

        # Désactiver les entrées de menu
        for widget in self.menu_frame.winfo_children():
            if not isinstance(widget, ttk.Menubutton):
                continue
            self._toggle_menu(widget, state)

        # Parcourir tous les widgets de la fenêtre
        for widget in self.winfo_children():
            if widget is self.menu_frame:
                continue
            self._toggle_widget_recursive(widget, state)

    def _toggle_menu(self, menu_button: ttk.Menubutton, state: cst):
        """Parcourt les entrées de menu et les active/désactive"""
        for menu in menu_button.winfo_children():
            if not isinstance(menu, ttk.Menu):
                continue

            for i in range(menu.index("end") + 1):
                try:
                    menu.entryconfig(i, state=state)
                except TclError:
                    pass  # Séparateurs n'ont pas de state

    def _toggle_widget_recursive(self, widget: Widget, state: cst):
        """Parcourt récursivement tous les widgets et les active/désactive"""
        # Ignorer le changement d'état pour les contrôles à ne pas verrouiller / déverouiller
        if widget in (self.run_button, self.output_text):
            return

        # Désactiver le widget s'il a un attribut 'state'
        try:
            widget.configure(state=state)
        except TclError:
            pass  # Certains widgets ne supportent pas state

        # Parcourir récursivement les enfants
        for child in widget.winfo_children():
            self._toggle_widget_recursive(child, state)

    # ----------------------------------------------
    # Sélections fichiers
    # ----------------------------------------------
    def select_folder(self):
        """Ouvre une boîte de dialogue pour choisir le dossier source"""
        filename = filedialog.askdirectory(
            title="Sélectionner le dossier source",
            initialdir=self.get_initial_dir(self.folder_var.get()).parent,
        )
        if filename:
            self.folder_var.set(Path(filename))  # Path used to normalize filename

    def select_template_file(self):
        """Ouvre une boîte de dialogue pour choisir le fichier template"""
        filename = filedialog.askopenfilename(
            title="Sélectionner le fichier template SQLite",
            filetypes=[("Fichiers SQLite", "*.sqlite"), ("Tous les fichiers", "*.*")],
            initialdir=self.get_initial_dir(self.template_var.get()),
        )
        if filename:
            self.template_var.set(Path(filename))  # Path used to normalize filename

    def select_excel_file(self):
        """Ouvre une boîte de dialogue pour choisir le fichier Excel"""
        filename = filedialog.askopenfilename(
            title="Sélectionner le fichier Excel",
            filetypes=[("Fichiers Excel", "*.xlsx *.xls"), ("Tous les fichiers", "*.*")],
            initialdir=self.get_initial_dir(self.excel_var.get()),
        )
        if filename:
            self.excel_var.set(Path(filename))  # Path used to normalize filename

    def get_initial_dir(self, file: Path | str) -> Path:
        """Retourne le parent d'un Path valide (existe) sinon renvoi current working directory"""
        candidates: list[str] = [
            str(file),  # on teste en premier file
            self.template_var.get(),
            self.excel_var.get(),
            self.folder_var.get(),
        ]

        for candidate in candidates:
            if candidate not in (NO_FILE_SELECTED, NO_FOLDER_SELECTED) and Path(candidate).exists():
                file_path: Path = Path(candidate)
                return file_path if file_path.is_dir() else file_path.parent

        return Path.cwd()

    # ----------------------------------------------
    # Fonctions execution tache dans un thread
    # ----------------------------------------------
    def start_task(self):
        """Démarre le traitement dans un thread séparé"""
        # Vérifier que la tâche peut bien être lancée
        if not self._task_is_runnable():
            return

        # Effacement des messages précédents
        self.output_text.config(state=cst.NORMAL)
        self.output_text.delete("1.0", cst.END)
        self.output_text.config(state=cst.DISABLED)

        # Verrouilage de l'UI et prépration de la config
        self.processing = True
        self.run_button.config(text="Arrêter", bootstyle=cst.DANGER)
        self.toggle_controls(False)  # Désactiver tous les contrôles

        cfg: RunConfig = self._task_build_config()

        # Lancement du traitement dans un thread
        self.processing_thread = threading.Thread(target=self._start_task, args=(cfg,), daemon=True)
        self.processing_thread.start()

    def _task_is_runnable(self) -> bool:
        """Vérification que la tache peut être lancé"""

        # Anomalies bloquantes

        template: str = self.template_var.get()
        if template == NO_FILE_SELECTED or not Path(template).exists():
            self.logger.critical("Fichier template SQLite non sélectionné ou inexistant !")
            return False

        excel: str = self.excel_var.get()
        if excel == NO_FILE_SELECTED or not Path(excel).exists():
            self.logger.critical("Fichier Tables_Infos non sélectionné ou inexistant !")
            return False

        # Anomalies non bloquantes

        folder: str = self.folder_var.get()
        if folder == NO_FOLDER_SELECTED or not Path(folder).exists() or not Path(folder).is_dir():
            self.folder_var.set(Path.cwd())
            self.logger.warning("Pas de dossier source, utilisation par défaut du dossier courant !")

        invalid_vars = [v.ui_label or v.sql_name for v in self.merger.cfg._sql_variables if not v.value_is_valid()]
        if invalid_vars:
            msg = "Non bloquant mais les variables suivantes sont invalides :\n- " + "\n- ".join(invalid_vars)
            self.logger.warning(msg)

        return True

    def _task_build_config(self) -> RunConfig:
        """Construit la config pour executer la tache SQLite"""
        # récupération de la config pré construite
        cfg = self.merger.cfg

        # mise à jour des éléments modifiables dans l'UI (hors variables)
        cfg.default_folder = Path(self.folder_var.get())
        cfg.sqlite_template = Path(self.template_var.get())
        cfg.xl_tables_infos = Path(self.excel_var.get())

        return cfg

    def timer(self, start_time: datetime = None, stop: bool = False, wait_in_sec: int = 5):
        """Délègue l'affichage d'un timer au thread principal Tkinter (thread-safe)"""
        self.after(0, self._timer, start_time, stop, wait_in_sec)

    def _timer(self, start_time: datetime = None, stop: bool = False, wait_in_sec: int = 5):
        """Afficher un timer à la fin de la dernière ligne de log"""
        timer_tag = "timer_tag"
        elapsed = (datetime.now() - start_time).total_seconds() if start_time else 0
        timer_str = f" ({int(elapsed) // 60:02d}:{int(elapsed) % 60:02d})"

        # cancel previous scheduled timer to avoid multiple timers
        if self._timer_after_id is not None:
            self.after_cancel(self._timer_after_id)
            self._timer_after_id = None

        # clear previous timer display
        if self.output_text.tag_ranges(timer_tag):
            self.output_text.config(state=cst.NORMAL)
            self.output_text.delete(f"{timer_tag}.first", f"{timer_tag}.last")
            self.output_text.config(state=cst.DISABLED)

        # stop timer if requested (no rescheduling)
        if stop:
            return

        # display timer before last newline if wait time exceeded
        if elapsed >= wait_in_sec:
            self.log(timer_str, start_pos="end-2c", tag=timer_tag, end_char="")

        # schedule next timer update
        self._timer_after_id = self.after(1000, self.timer, start_time, stop, wait_in_sec)

    def _start_task(self, cfg: RunConfig):
        """Fonction qui exécute le traitement SQLite dans un thread secondaire"""
        try:
            self.merger.run(cfg)
        except UserInterruptedError:
            pass
        except Exception as e:
            self.log(traceback.format_exc())
            self.logger.critical(f"Problème dans l'execution de la tâche : {str(e)}")
        finally:
            self.stop_task()
            self.after(0, self.focus_force)  # Forcer le focus à partir du thread principal

    def stop_task(self, kill: bool = False):
        """Arrête le traitement"""

        def finalize(msg: str = ""):
            self.is_stopping = False
            self.processing = False
            self.timer(stop=True)
            self.run_button.config(text="Démarrer", bootstyle=cst.PRIMARY)
            self.toggle_controls(True)  # réactiver tous les contrôles
            if msg:
                self.log(msg)

        def wait_for_thread_ending():
            if self.processing_thread and self.processing_thread.is_alive():
                self.after(100, wait_for_thread_ending)
            else:
                finalize(msg=">>> Tâche arrêtée !")

        if kill:
            if self.is_stopping or not self.processing:
                return  # arrêt déjà en cours ou pas de process en cours

            self.is_stopping = True
            self.timer(datetime.now())
            self.log(">>> Arrêt en cours...")
            self.merger.stop_event.set()
            wait_for_thread_ending()
            return

        self.after(0, finalize)

    # ----------------------------------------------
    # Fonctions autres
    # ----------------------------------------------
    def on_closing(self):
        """Arrêter proprement en killant avec stop_task() le traitement si il est est en cours"""
        if not self.is_stopping:
            self.stop_task(kill=True)

        if self.processing:
            self.after(100, self.on_closing)
            return

        self.destroy()

    def editable_vars_exist(self) -> bool:
        """indique si des variables éditables existent"""
        return len(self.user_vars + self.advanced_vars) > 0

    def open_vars_dialog(self, start_after: bool = False):
        """Ouvre la fenêtre d'édition des variables"""

        def callback_func(canceled: bool):
            # si annulé, ne rien faire de plus
            if canceled:
                return
            # démarrage tâche si demandé
            if start_after:
                self.start_task()

        AdvancedSettings(self, self.merger.cfg, callback=lambda canceled: callback_func(canceled))

    def open_about(self):
        AboutWindow(self)

    def log(self, message: str, start_pos: str = cst.END, tag: str = "", end_char: str = "\n"):
        """Délègue au thread principal l'ajout d'un message dans la textbox (remplace print)"""
        args = (message, start_pos, tag, end_char)
        self.after(0, self._log, *args)  # utilisé le thread principal (TkInter pas thread-safe)

    def _log(self, message: str, start_pos: str = cst.END, tag: str = "", end_char: str = "\n"):
        """Ajoute un message dans la textbox (remplace print)"""
        self.output_text.config(state=cst.NORMAL)
        self.output_text.insert(start_pos, message + end_char, tag)
        self.output_text.see(cst.END)  # Auto-scroll vers le bas
        self.output_text.config(state=cst.DISABLED)


class AdvancedSettings(ttk.Toplevel):
    def __init__(self, parent: ttk.Window, cfg: RunConfig, callback: Callable[[bool], None] = None):
        super().__init__(parent)

        self.parent = parent
        self.transient(self.parent)
        self.grab_set()

        self.callback_func: Callable[[bool], None] = callback  # callback avec info si canceled ou pas

        self.original_cfg = cfg
        self.working_vars: list[Variable] = cfg.get_editable_vars()
        self.hidden_vars: list[Variable] = cfg.get_uneditable_vars()

        self.working_vars.sort(key=lambda v: v.level.priority)

        self._setup_ui()

    # ----------------------------------------------
    # Création UI
    # ----------------------------------------------
    def _setup_ui(self):
        self.title("Paramètres avancés - Variables SQL")

        width, height = 500, 450
        self.geometry(f"{width}x{height}")
        if self.parent:
            self.geometry(
                f"+{self.parent.winfo_x() + (self.parent.winfo_width() - width) // 2}"
                + f"+{self.parent.winfo_y() + (self.parent.winfo_height() - height) // 2}"
            )

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=cst.BOTH, expand=True)

        self._setup_tree(frame)
        self._setup_buttons(frame)
        self._setup_binds()

        # Alimentation tree et focus
        self.populate_tree()

        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])

        self.after(100, lambda: self.tree.focus_set())  # délai pour attendre affichage complet

    def _setup_tree(self, parent):
        # Style treeview avec hauteur de ligne plus grande
        self.custom_style = ttk.Style()
        self.custom_style.configure("Custom.Treeview", rowheight=30)

        # Frame dédié pour tree
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=cst.BOTH, expand=True)

        # Création treeview
        columns = ("name", "value", "ctrl")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show=cst.HEADINGS, selectmode=cst.BROWSE)
        self.tree.configure(style="Custom.Treeview")

        scrollbar = ttk.Scrollbar(tree_frame, orient=cst.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=cst.LEFT, fill=cst.BOTH, expand=True)
        scrollbar.pack(side=cst.RIGHT, fill=cst.Y)

        # Configuration des colonnes
        self.tree.heading("name", text="Variable", anchor=cst.W)
        self.tree.column("name", width=150, stretch=True)

        self.tree.heading("value", text="Valeur", anchor=cst.W)
        self.tree.column("value", width=100, stretch=True)

        self.tree.heading("ctrl", text="État", anchor=cst.CENTER)
        self.tree.column("ctrl", width=50, stretch=False, anchor=cst.CENTER)  # Fixe et centrée

    def _setup_buttons(self, parent):
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", pady=15)

        self.btn_more = ttk.Button(btn_frame, text="+", width=2, command=self.show_more, bootstyle=cst.SECONDARY)
        btn_apply = ttk.Button(btn_frame, text="Valider", width=10, command=self.apply, bootstyle=cst.PRIMARY)
        btn_cancel = ttk.Button(btn_frame, text="Annuler", width=10, command=self.closing, bootstyle=cst.DANGER)

        info_label = ttk.Label(btn_frame, text="Nb : double cliquer une ligne pour l'éditer", bootstyle=cst.LIGHT)
        info_label.config(wraplength=200, justify=cst.LEFT)

        self.btn_more.pack(side=cst.LEFT)
        info_label.pack(side=cst.LEFT, expand=cst.FALSE, padx=(5, 5), pady=(0, 4))
        btn_cancel.pack(side=cst.RIGHT)
        btn_apply.pack(side=cst.RIGHT, padx=(0, 10))

    def _setup_binds(self):
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_enter_pressed)
        self.tree.bind("<KP_Enter>", self._on_enter_pressed)

        # Fermeture de l'application
        self.protocol("WM_DELETE_WINDOW", self.closing)

    # ----------------------------------------------
    # Interaction UI
    # ----------------------------------------------
    def _on_enter_pressed(self, event):
        """Lance l'édition quand on appuie sur Entrée"""
        selected = self.tree.selection()
        if selected:
            self._open_edit_window(selected[0])

    def _on_double_click(self, event):
        """Lance l'édition au double-clic sur la cellule valeur"""
        region = self.tree.identify("region", event.x, event.y)
        # column = self.tree.identify_column(event.x)
        if region == "cell":  # and column == "#2":
            row_id = self.tree.identify_row(event.y)
            self._open_edit_window(row_id)

    def _open_edit_window(self, row_id):
        """Logique d'édition avec Entry flottante"""
        x, y, width, height = self.tree.bbox(row_id, "#2")  # colonne valeur ciblée

        value = self.tree.set(row_id, "value")

        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, value)
        entry.focus_set()
        entry.select_range(0, cst.END)  # Sélectionne tout le texte

        def save_edit(event=None):
            new_value = entry.get()
            idx = int(row_id)
            self.working_vars[idx].value = new_value

            # mise à jour UI
            status = self._get_value_status(self.working_vars[idx])
            self.tree.item(row_id, values=(self.tree.set(row_id, "name"), new_value, status))
            close_edit()

        def close_edit(event=None):
            entry.destroy()
            self.tree.focus_set()

        entry.bind("<Return>", save_edit)
        entry.bind("<KP_Enter>", save_edit)
        entry.bind("<FocusOut>", close_edit)
        entry.bind("<Escape>", close_edit)
        self.tree.bind("<MouseWheel>", close_edit)

    def populate_tree(self):
        # On nettoie avant de remplir
        for item in self.tree.get_children():
            self.tree.delete(item)

        for idx, var in enumerate(self.working_vars):
            label = var.ui_label if var.ui_label else var.sql_name
            status = self._get_value_status(var)
            self.tree.insert("", "end", iid=str(idx), values=(label, var.value, status))

    def _get_value_status(self, var: Variable) -> str:
        return "✓" if var.value_is_valid() else "✗"

    # ----------------------------------------------
    # Fonctions autres
    # ----------------------------------------------
    def show_more(self):
        """Montrer et permettre de modifier les variables internes"""
        self.btn_more.configure(state=cst.DISABLED)
        self.working_vars.extend(self.hidden_vars)
        self.hidden_vars = []
        self.populate_tree()
        msg = (
            "Attention !\nAffichage de toutes les variables, "
            + "y compris celles internes qui ne sont pas sensées être changées..."
        )
        messagebox.showwarning(title="Variables", message=msg, parent=self)

    def apply(self):
        # Vérification finale
        invalid_vars = [v.ui_label or v.sql_name for v in self.working_vars if not v.value_is_valid()]

        if invalid_vars:
            msg = "Non bloquant mais les variables suivantes sont invalides :\n- " + "\n- ".join(invalid_vars)
            messagebox.showwarning(title="Variables invalides", message=msg, parent=self)

        # Application des changements à l'objet original
        self.original_cfg._sql_variables = self.working_vars + self.hidden_vars
        self.closing(canceled=False)

    def closing(self, canceled: bool = True):
        """Fermeture fenêtre"""
        self.callback_func(canceled)
        self.destroy()


class LogHandler(logging.Handler):
    """Handler pour rediriger vers Tkinter"""

    def __init__(self, app: App):
        super().__init__()
        self.app: App = app

        # définition du format
        self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S"))

        # ajout du handler (self) au logger du module merger
        logger = logging.getLogger(LOGGER_NAME)
        logger.addHandler(self)
        logger.setLevel(logging.INFO)

    def emit(self, record):
        action = getattr(record, "action", None)
        if action is TimerAction.START:
            start_time: datetime = record.__dict__.get("start_time", None)
            wait_in_sec: int = record.__dict__.get("wait_in_sec", 5)
            self.app.timer(start_time=start_time, wait_in_sec=wait_in_sec)
        elif action is TimerAction.STOP:
            self.app.timer(stop=True)
        else:
            msg = self.format(record)
            self.app.log(msg)


if __name__ == "__main__":
    args = parse_arguments()  # Parser les arguments ligne de commande

    app = App(args.config, args.template, args.infos)
    app.mainloop()
