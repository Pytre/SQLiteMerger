import ttkbootstrap as tk
import ttkbootstrap.constants as cst
import webbrowser
from pathlib import Path
from tkinter import Event

import about


class AboutWindow(tk.Toplevel):
    def __init__(self, parent: tk.Toplevel = None):
        super().__init__(parent)
        self.parent: tk.Toplevel = parent
        if self.parent:
            self.focus_set()
            self.transient(self.parent)
            self.grab_set()
        else:
            self.master.withdraw()

        self._setup_ui()
        self._events_binds()

    # ------------------------------------------------------------------------------------------
    # Création de l'interface
    # ------------------------------------------------------------------------------------------
    def _setup_ui(self):
        self.title(f"{about.APP_NAME} - À propos")
        self._setup_position()
        self.resizable(False, False)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.top_frame = tk.Frame(self)
        self.license_frame = tk.Labelframe(self)
        self.bottom_frame = tk.Frame(self)

        self.top_frame.grid(row=0, column=0, padx=5, pady=10, sticky=cst.NSEW)
        self.license_frame.grid(row=1, column=0, padx=5, pady=0, sticky=cst.NSEW)
        self.bottom_frame.grid(row=2, column=0, padx=5, pady=10, sticky=cst.NSEW)

        self._setup_top_frame()
        self._setup_license_frame()
        self._setup_bottom_frame()

    def _setup_position(self):
        width, height = 450, 375
        if self.parent:
            self.geometry(f"{width}x{height}")
            if self.parent:
                self.geometry(
                    f"+{self.parent.winfo_x() + (self.parent.winfo_width() - width) // 2}"
                    + f"+{self.parent.winfo_y() + (self.parent.winfo_height() - height) // 2}"
                )
        else:
            self.geometry(f"{width}x{height}")

    def _setup_top_frame(self):
        self.top_frame.rowconfigure(0, weight=1)
        self.top_frame.columnconfigure(2, weight=1)

        logo_file = Path(__file__).parent / "res" / "app_icon.png"
        self.logo_img = tk.PhotoImage(file=logo_file).subsample(8, 8)

        logo_label = tk.Label(self.top_frame, image=self.logo_img, justify=cst.CENTER)
        app_label = tk.Label(self.top_frame, text=about.APP_NAME, font=("TkDefaultFont", 20, "bold"), anchor=cst.SW)
        app_version = about.APP_VERSION if not about.APP_STATUS else f"{about.APP_VERSION} {about.APP_STATUS}"
        version_label = tk.Label(
            self.top_frame,
            text=f"Version : {app_version} - Build {about.APP_BUILD}",
            font=("TkDefaultFont", 8, "normal"),
            anchor=cst.NE,
        )
        author_label = tk.Label(
            self.top_frame,
            text=f"Copyright (C) {about.COPYRIGHT_YEAR} / Created by {about.AUTHOR}",
            font=("TkDefaultFont", 8, "normal"),
            anchor=cst.NW,
        )
        link_label = tk.Label(
            self.top_frame,
            text=about.HOMEPAGE_LINK,
            font=("TkDefaultFont", 8, "underline"),
            cursor="hand2",
            bootstyle=cst.INFO,
        )

        link_label.bind("<Button-1>", lambda e: webbrowser.open_new_tab(about.HOMEPAGE_LINK))

        logo_label.grid(row=0, column=0, rowspan=3, padx=10, pady=0, sticky=cst.NSEW)
        app_label.grid(row=0, column=1, padx=4, pady=0, sticky=cst.NSEW)
        version_label.grid(row=0, column=2, padx=4, pady=0, sticky=cst.NE)
        author_label.grid(row=1, column=1, columnspan=2, padx=4, pady=0, sticky="swe")
        link_label.grid(row=2, column=1, columnspan=2, padx=4, pady=0, sticky="nwe")

    def _setup_license_frame(self):
        self.license_frame.rowconfigure(0, weight=1)
        self.license_frame.columnconfigure(0, weight=1)

        title_label = tk.Label(self.license_frame, text=about.LICENSE_NAME, font=("Helvetica", 10, "bold"))
        self.license_frame.config(labelwidget=title_label, borderwidth=2, labelanchor=cst.N)

        license_textbox = tk.Text(self.license_frame, wrap=cst.WORD, font=("TkDefaultFont", 8, "normal"))
        license_textbox.insert("0.0", about.LICENSE_TEXT)
        license_textbox.configure(state=cst.DISABLED)

        license_textbox.grid(row=0, column=0, padx=4, pady=4, sticky=cst.NSEW)

    def _setup_bottom_frame(self):
        self.bottom_frame.rowconfigure(0, weight=1)
        self.bottom_frame.columnconfigure(0, weight=1)
        self.bottom_frame.columnconfigure(2, weight=1)

        ok_btn = tk.Button(self.bottom_frame, text="Ok", command=self.app_exit, bootstyle=cst.PRIMARY)
        ok_btn.grid(row=0, column=1, padx=4, pady=4, sticky=cst.NSEW)

    # ------------------------------------------------------------------------------------------
    # Définition des évènements générer par les traitements
    # ------------------------------------------------------------------------------------------
    def _events_binds(self):
        self.protocol("WM_DELETE_WINDOW", self.app_exit)  # arrêter le programme quand fermeture de la fenêtre

    # ------------------------------------------------------------------------------------------
    # Autres traitements
    # ------------------------------------------------------------------------------------------
    def app_exit(self, _: Event = None):
        self.destroy()

        if self.parent is None:
            self.quit()


if __name__ == "__main__":
    my_app = AboutWindow()
    my_app.mainloop()
