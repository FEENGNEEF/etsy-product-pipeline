# pyright: ignore

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
import threading
import subprocess
import shutil
import zipfile
import logging
from pathlib import Path
import json
import uuid
import numpy as np
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError, ImageEnhance, ImageTk
from moviepy.editor import ImageSequenceClip
from math import sqrt
import re

VALID_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')

SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = SCRIPT_DIR / 'settings_unified.json'
WAIFU2X_EXE_FIXED = os.getenv('WAIFU2X_EXE', '')
REALESRGAN_EXE_FIXED = os.getenv('REALESRGAN_EXE', '')
REALESRGAN_MODEL_DIR_FIXED = os.getenv('REALESRGAN_MODEL_DIR', '')
REALESRGAN_MODEL_NAME_FIXED = os.getenv('REALESRGAN_MODEL_NAME', 'realesr-general-x4v3')

if hasattr(Image, 'Resampling'):
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
else:
    RESAMPLE_LANCZOS = getattr(Image, 'LANCZOS', 1)


def find_baskerville_font():
    """Vrati absolutni cestu k Baskerville Old Face TTF (hleda ve systemovych i uzivatelskych adresarich fontu)."""
    win_fonts = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Fonts"
    user_fonts = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
    candidates = []
    for folder in (win_fonts, user_fonts):
        if folder.exists():
            for file in folder.glob("*"):
                if file.name.lower() in ("baskvill.ttf", "baskerville old face.ttf"):
                    candidates.append(file)
    if not candidates:
        for folder in (win_fonts, user_fonts):
            if folder.exists():
                candidates.extend(folder.glob("*baskerville*face*.ttf"))
                candidates.extend(folder.glob("*baskvill*.ttf"))
    return str(candidates[0]) if candidates else None


class FormatPolicy:
    @staticmethod
    def output_ext_for_input(input_ext):
        return '.png' if input_ext == '.png' else '.jpg'

    @staticmethod
    def output_ext_for_choice(fmt: str):
        fmt_l = (fmt or '').lower()
        return '.png' if fmt_l == 'png' else '.jpg'

    @staticmethod
    def waifu2x_format(input_ext):
        return 'png' if input_ext == '.png' else 'jpg'

    @staticmethod
    def realesrgan_format(input_ext):
        return 'png' if input_ext == '.png' else 'jpg'

    @staticmethod
    def save_lightroom(img, output_path, output_ext):
        if output_ext == '.png':
            img.save(output_path, format='PNG', dpi=(300, 300))
        else:
            img.save(output_path, format='JPEG', quality=70, dpi=(300, 300))

    @staticmethod
    def prepare_for_watermark(img, input_ext):
        if input_ext == '.png':
            background = Image.new('RGBA', img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(background, img)
        return img.convert('RGBA')

    @staticmethod
    def save_enhanced(img, output_path, output_ext):
        if output_ext == '.png':
            img.save(output_path, format='PNG')
        else:
            img.save(output_path, format='JPEG', quality=70)


class NamingStrategy:
    UNDERSCORE_RE = re.compile(r'_\d+$')
    SPACE_NUM_RE = re.compile(r'\s\d+$')

    @classmethod
    def detect_style(cls, stems):
        underscore = sum(1 for stem in stems if cls.UNDERSCORE_RE.search(stem))
        space = sum(1 for stem in stems if cls.SPACE_NUM_RE.search(stem))
        if underscore > space:
            return 'underscore'
        if space > underscore:
            return 'space'
        return 'mixed'

    @classmethod
    def group_name(cls, stem, style):
        if style == 'underscore':
            return cls.UNDERSCORE_RE.sub('', stem)
        if style == 'space':
            parts = stem.split(' ')
            if len(parts) <= 1:
                return stem
            return ' '.join(parts[:-1])
        if cls.UNDERSCORE_RE.search(stem):
            return cls.UNDERSCORE_RE.sub('', stem)
        if cls.SPACE_NUM_RE.search(stem):
            parts = stem.split(' ')
            if len(parts) > 1:
                return ' '.join(parts[:-1])
        return stem


class ImageProcessingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("unziprename_and_WTMRK")
        self.setup_logging()
        self.settings = {}
        self.load_settings()

        # Phase 0/1 settings (persisted), but project path is chosen each run.
        self.pipeline_mode_var = tk.StringVar(value=self.settings.get('pipeline_mode', 'cliparts'))
        self.rawprep_unzip_var = tk.BooleanVar(value=self.settings.get('rawprep_unzip', True))
        self.rawprep_skip_unzip_var = tk.BooleanVar(value=self.settings.get('rawprep_skip_unzip_if_exists', True))
        self.rawprep_delete_zip_var = tk.BooleanVar(value=self.settings.get('rawprep_delete_zip_after_unzip', False))
        self.rawprep_flatten_var = tk.BooleanVar(value=self.settings.get('rawprep_flatten_rename', True))
        self.rawprep_delete_empty_var = tk.BooleanVar(value=self.settings.get('rawprep_delete_empty_folders', True))
        self.rawprep_dry_run_var = tk.BooleanVar(value=self.settings.get('rawprep_dry_run', False))

        self._mockup_enabled_prev = None
        self._run_all_requested = False
        self.cancel_processing = False
        self.image_paths = []
        self.project_folder = ""
        self.selected_images_for_brightening = []
        self.mockup_enabled = tk.BooleanVar(value=self.settings.get('mockup_enabled', False))
        self.mockups = self.settings.get('mockups', [])
        self.mockup_images = {}
        self.mockup_display_images = {}
        self.mockup_maps = self.settings.get('mockup_maps', {})
        self.mockup_vars = {
            path: {'selected': tk.BooleanVar(value=self.settings.get('mockup_selections', {}).get(path, True))}
            for path in self.mockups
        }
        self.current_mockup_path = None
        self.copyright_enabled = tk.BooleanVar(value=self.settings.get('copyright_enabled', False))
        self.copyright_image = None
        self.copyright_path = self.settings.get('copyright_path', '')
        self.copyright_map = self.settings.get('copyright_map', None)
        self.copyright_rect = None
        self.drawing_copyright_map = False
        self.canvas_width = 400
        self.canvas_height = 400
        self.rect = None
        self.naming_style = None
        self.setup_ui()
        self.start_time = 0.0
        self.initialize_mockups()

    def setup_logging(self):
        logging.basicConfig(filename=str(SCRIPT_DIR / 'app.log'), level=logging.INFO,
                            format='%(asctime)s %(levelname)s:%(message)s')

    def load_settings(self):
        # Keep settings next to this script (not current working directory)
        self.settings_file = str(SETTINGS_PATH)
        self.settings = {
            'zip_limit': 20 * 1024 * 1024,
            'create_video': False,
            'waifu2x_exe': WAIFU2X_EXE_FIXED,
            'model_dir': '',
            'scale_factor': 2,
            'denoise_level': 0,
            'author_name': '',
            'brighten_twice': False,
            'selected_images_for_brightening': [],
            'mockup_enabled': False,
            'mockups': [],
            'mockup_maps': {},
            'mockup_selections': {},
            'copyright_enabled': False,
            'copyright_path': '',
            'copyright_map': None,
            'video_duration': 4.0,

            # New: pipeline mode + RAW prep options
            'pipeline_mode': 'cliparts',
            'rawprep_unzip': True,
            'rawprep_skip_unzip_if_exists': True,
            'rawprep_delete_zip_after_unzip': False,
            'rawprep_flatten_rename': True,
            'rawprep_delete_empty_folders': True,
            'rawprep_dry_run': False,

            # New: upscale output format (png/jpg)
            'upscale_output_format': 'png',
            'upscale_jpeg_quality': 100,
        }
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    loaded_settings = json.load(f)
                    self.settings.update(loaded_settings)
                # Enforce fixed Waifu2x path.
                self.settings['waifu2x_exe'] = WAIFU2X_EXE_FIXED
                logging.info("Nastaveni nactena ze souboru settings_unified.json")
                valid_mockups = []
                for mockup_path in self.settings.get('mockups', []):
                    if os.path.exists(mockup_path):
                        valid_mockups.append(mockup_path)
                    else:
                        logging.warning(f"Mockup {mockup_path} neexistuje a byl odstranen ze seznamu.")
                self.settings['mockups'] = valid_mockups
            except Exception as e:
                logging.error(f"Chyba pri nacitani nastaveni: {e}")
                messagebox.showerror("Chyba", f"Nelze nacist nastaveni: {e}")

    def save_settings(self):
        self.settings['scale_factor'] = int(self.scale_entry.get()) if self.scale_entry.get().isdigit() else 2
        self.settings['denoise_level'] = int(self.denoise_entry.get()) if self.denoise_entry.get().isdigit() else 0
        self.settings['author_name'] = self.author_entry.get()
        self.settings['brighten_twice'] = self.brighten_twice_var.get()
        self.settings['selected_images_for_brightening'] = self.selected_images_for_brightening
        self.settings['create_video'] = self.create_video_var.get()
        self.settings['mockup_enabled'] = self.mockup_enabled.get()
        self.settings['mockups'] = self.mockups
        self.settings['mockup_maps'] = self.mockup_maps
        self.settings['mockup_selections'] = {path: var['selected'].get() for path, var in self.mockup_vars.items()}
        self.settings['copyright_enabled'] = self.copyright_enabled.get()
        self.settings['copyright_path'] = self.copyright_path or ''
        self.settings['copyright_map'] = self.copyright_map
        self.settings['pipeline_mode'] = self.pipeline_mode_var.get()
        self.settings['rawprep_unzip'] = self.rawprep_unzip_var.get()
        self.settings['rawprep_skip_unzip_if_exists'] = self.rawprep_skip_unzip_var.get()
        self.settings['rawprep_delete_zip_after_unzip'] = self.rawprep_delete_zip_var.get()
        self.settings['rawprep_flatten_rename'] = self.rawprep_flatten_var.get()
        self.settings['rawprep_delete_empty_folders'] = self.rawprep_delete_empty_var.get()
        self.settings['rawprep_dry_run'] = self.rawprep_dry_run_var.get()
        self.settings['upscale_output_format'] = 'png' if self.upscale_output_png_var.get() else 'jpg'
        # Keep default consistent with Waifu GUI screenshot.
        try:
            self.settings['upscale_jpeg_quality'] = int(self.settings.get('upscale_jpeg_quality', 100))
        except Exception:
            self.settings['upscale_jpeg_quality'] = 100

        # Keep Waifu2x path fixed.
        self.settings['waifu2x_exe'] = WAIFU2X_EXE_FIXED
        try:
            self.settings['video_duration'] = float(self.settings.get('video_duration', 4.0))
        except ValueError:
            self.settings['video_duration'] = 4.0
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f)
            logging.info("Nastaveni ulozena do souboru settings_unified.json")
        except Exception as e:
            logging.error(f"Chyba pri ukladani nastaveni: {e}")
            messagebox.showerror("Chyba", f"Nelze ulozit nastaveni: {e}")

    def initialize_mockups(self):
        for mockup_path in self.mockups:
            try:
                mockup_image = Image.open(mockup_path)
                self.mockup_images[mockup_path] = mockup_image
                display_image = mockup_image.copy()
                display_image.thumbnail((self.canvas_width, self.canvas_height), resample=RESAMPLE_LANCZOS)  # type: ignore[arg-type]
                self.mockup_display_images[mockup_path] = display_image
                if mockup_path not in self.mockup_vars:
                    self.mockup_vars[mockup_path] = {
                        'selected': tk.BooleanVar(value=self.settings.get('mockup_selections', {}).get(mockup_path, True))
                    }
                logging.info(f"Nacten mockup: {mockup_path}")
            except Exception as e:
                logging.error(f"Chyba pri nacitani mockupu {mockup_path}: {e}")
                self.mockups.remove(mockup_path)
                continue
        if self.copyright_path and os.path.exists(self.copyright_path):
            try:
                self.copyright_image = Image.open(self.copyright_path)
                logging.info(f"Nacten copyright obrazek: {self.copyright_path}")
            except Exception as e:
                logging.error(f"Chyba pri nacitani copyright obrazku {self.copyright_path}: {e}")
                self.copyright_path = ''
                self.copyright_image = None
        self.create_mockup_buttons()

    def setup_ui(self):
        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Nastaveni", command=self.open_settings_window)
        menubar.add_cascade(label="Moznosti", menu=settings_menu)
        self.root.config(menu=menubar)

        main_container = ttk.Frame(self.root, padding="10")
        main_container.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_container)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

        project_frame = ttk.LabelFrame(left_frame, text="Projektova slozka")
        project_frame.pack(fill=tk.X, pady=5)

        ttk.Button(project_frame, text="Vybrat slozku projektu", command=self.select_project_folder).pack(padx=5, pady=5)
        self.project_label = ttk.Label(project_frame, text="Zadna slozka projektu vybrana.")
        self.project_label.pack(padx=5, pady=5)

        mode_frame = ttk.LabelFrame(left_frame, text="Rezim")
        mode_frame.pack(fill=tk.X, pady=5)
        ttk.Radiobutton(
            mode_frame,
            text="CLIPARTS (bez mockupu)",
            variable=self.pipeline_mode_var,
            value='cliparts',
            command=self.on_pipeline_mode_changed,
        ).pack(anchor='w', padx=5, pady=2)
        ttk.Radiobutton(
            mode_frame,
            text="DESIGNS_TRANSPARENT (mockupy ok)",
            variable=self.pipeline_mode_var,
            value='designs_transparent',
            command=self.on_pipeline_mode_changed,
        ).pack(anchor='w', padx=5, pady=2)

        rawprep_frame = ttk.LabelFrame(left_frame, text="Faze 1 - RAW prep")
        rawprep_frame.pack(fill=tk.X, pady=5)
        self.rawprep_unzip_check = ttk.Checkbutton(
            rawprep_frame,
            text="Unzip .zip v RAW do slozek",
            variable=self.rawprep_unzip_var,
            command=self.on_rawprep_option_changed,
        )
        self.rawprep_unzip_check.pack(anchor='w', padx=5, pady=2)

        self.rawprep_skip_check = ttk.Checkbutton(
            rawprep_frame,
            text="Skip unzip pokud slozka existuje",
            variable=self.rawprep_skip_unzip_var,
            command=self.on_rawprep_option_changed,
        )
        self.rawprep_skip_check.pack(anchor='w', padx=20, pady=2)

        self.rawprep_delete_zip_check = ttk.Checkbutton(
            rawprep_frame,
            text="Smazat zip po rozbaleni",
            variable=self.rawprep_delete_zip_var,
            command=self.on_rawprep_option_changed,
        )
        self.rawprep_delete_zip_check.pack(anchor='w', padx=20, pady=2)

        self.rawprep_flatten_check = ttk.Checkbutton(
            rawprep_frame,
            text="Prejmenovat + presunout obrazky do RAW root (Nazev_1)",
            variable=self.rawprep_flatten_var,
            command=self.on_rawprep_option_changed,
        )
        self.rawprep_flatten_check.pack(anchor='w', padx=5, pady=2)

        self.rawprep_delete_empty_check = ttk.Checkbutton(
            rawprep_frame,
            text="Smazat prazdne slozky po presunu",
            variable=self.rawprep_delete_empty_var,
            command=self.on_rawprep_option_changed,
        )
        self.rawprep_delete_empty_check.pack(anchor='w', padx=20, pady=2)

        self.rawprep_dry_run_check = ttk.Checkbutton(
            rawprep_frame,
            text="Dry run (bez zmen) - jen vypise akce",
            variable=self.rawprep_dry_run_var,
            command=self.on_rawprep_option_changed,
        )
        self.rawprep_dry_run_check.pack(anchor='w', padx=5, pady=2)

        waifu_frame = ttk.LabelFrame(left_frame, text="Nastaveni Waifu2x")
        waifu_frame.pack(fill=tk.X, pady=5)

        ttk.Label(waifu_frame, text="Pocet zvetseni (2, 3 nebo 4):").grid(row=0, column=0, padx=5, pady=5)
        self.scale_entry = ttk.Entry(waifu_frame)
        self.scale_entry.insert(0, str(self.settings.get('scale_factor', 2)))
        self.scale_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(waifu_frame, text="Uroven odstraneni sumu (-1 az 3) [ignorovano pro RealESRGAN]:").grid(row=1, column=0, padx=5, pady=5)
        self.denoise_entry = ttk.Entry(waifu_frame)
        self.denoise_entry.insert(0, str(self.settings.get('denoise_level', 0)))
        self.denoise_entry.grid(row=1, column=1, padx=5, pady=5)

        self.upscale_output_png_var = tk.BooleanVar(value=(self.settings.get('upscale_output_format', 'png') == 'png'))
        ttk.Checkbutton(
            waifu_frame,
            text="Upscale vystup jako PNG (jinak JPG)",
            variable=self.upscale_output_png_var,
            command=self.save_settings,
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky='w')

        author_frame = ttk.LabelFrame(left_frame, text="Nastaveni autora")
        author_frame.pack(fill=tk.X, pady=5)

        ttk.Label(author_frame, text="Autor:").grid(row=0, column=0, padx=5, pady=5)
        self.author_entry = ttk.Entry(author_frame)
        self.author_entry.insert(0, self.settings.get('author_name', ''))
        self.author_entry.grid(row=0, column=1, padx=5, pady=5)

        options_frame = ttk.LabelFrame(left_frame, text="Moznosti zpracovani")
        options_frame.pack(fill=tk.X, pady=5)

        self.create_video_var = tk.BooleanVar(value=self.settings.get('create_video', False))
        ttk.Checkbutton(options_frame, text="Vytvorit video z obrazku (lightroom watermark)",
                        variable=self.create_video_var).pack(padx=5, pady=5)

        self.brighten_twice_var = tk.BooleanVar(value=self.settings.get('brighten_twice', False))
        self.brighten_twice_check = ttk.Checkbutton(options_frame, text="Vybelit 2x",
                                                    variable=self.brighten_twice_var,
                                                    command=self.toggle_select_images_for_brightening)
        self.brighten_twice_check.pack(padx=5, pady=5)

        self.select_images_brighten_button = ttk.Button(options_frame, text="Vybelit 2x jen nektere",
                                                        command=self.select_images_for_brightening)
        self.select_images_brighten_button.pack(padx=5, pady=5)
        self.select_images_brighten_button.config(state='disabled')

        control_frame = ttk.Frame(left_frame)
        control_frame.pack(fill=tk.X, pady=5)

        ttk.Button(control_frame, text="RUN ALL", command=self.run_all).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(control_frame, text="Jen faze 2", command=self.run_processing).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(control_frame, text="Jen RAW prep", command=self.run_raw_prep_only).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(control_frame, text="Otevrit slozku projektu", command=self.open_project_folder).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(control_frame, text="Zrusit zpracovani", command=self.cancel_processing_task).pack(side=tk.LEFT, padx=5, pady=5)

        self.progress = ttk.Progressbar(left_frame, orient=tk.HORIZONTAL, length=300, mode='determinate')
        self.progress.pack(pady=10)
        self.progress_label = ttk.Label(left_frame, text="")
        self.progress_label.pack()

        self.eta_label = ttk.Label(left_frame, text="")
        self.eta_label.pack()

        self.mockup_frame = ttk.LabelFrame(main_container, text="Mockuper")
        self.mockup_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)

        self.mockup_enabled_check = ttk.Checkbutton(self.mockup_frame, text="Spustit Mockuper",
                                                    variable=self.mockup_enabled, command=self.toggle_mockup_settings)
        self.mockup_enabled_check.pack(padx=5, pady=5)

        self.mockup_controls_frame = ttk.Frame(self.mockup_frame)
        self.mockup_controls_frame.pack(fill=tk.X, pady=5)

        self.load_mockups_button = ttk.Button(self.mockup_controls_frame, text="Nacist Mockupy",
                                              command=self.load_mockups)
        self.load_mockups_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.copyright_check = ttk.Checkbutton(self.mockup_controls_frame, text="Pridat Copyright",
                                               variable=self.copyright_enabled, command=self.toggle_copyright)
        self.copyright_check.pack(side=tk.LEFT, padx=5, pady=5)

        self.load_copyright_button = ttk.Button(self.mockup_controls_frame, text="Vybrat Copyright",
                                                command=self.load_copyright_image)
        self.load_copyright_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.canvas = tk.Canvas(self.mockup_frame, width=self.canvas_width, height=self.canvas_height)
        self.canvas.pack(pady=5)
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)

        self.mockup_buttons_frame = ttk.Frame(self.mockup_frame)
        self.mockup_buttons_frame.pack(fill=tk.X, pady=5)

        self.toggle_mockup_settings()
        self.create_mockup_buttons()

        self.on_pipeline_mode_changed(save=False)
        self.on_rawprep_option_changed(save=False)

    def toggle_select_images_for_brightening(self):
        if self.brighten_twice_var.get():
            self.select_images_brighten_button.config(state='normal')
        else:
            self.select_images_brighten_button.config(state='disabled')
            self.selected_images_for_brightening = []
        self.save_settings()

    def toggle_mockup_settings(self):
        if self.pipeline_mode_var.get() == 'cliparts':
            state = 'disabled'
        else:
            state = 'normal' if self.mockup_enabled.get() else 'disabled'
        for widget in self.mockup_controls_frame.winfo_children():
            widget.configure(state=state)  # type: ignore[call-arg]
        self.canvas.configure(state=state)  # type: ignore[call-arg]
        for widget in self.mockup_buttons_frame.winfo_children():
            for child in widget.winfo_children():
                child.configure(state=state)  # type: ignore[call-arg]
        if self.copyright_enabled.get():
            self.load_copyright_button.configure(state='normal')  # type: ignore[call-arg]
        else:
            self.load_copyright_button.configure(state='disabled')  # type: ignore[call-arg]
        self.save_settings()

    def toggle_copyright(self):
        state = 'normal' if self.copyright_enabled.get() else 'disabled'
        self.load_copyright_button.configure(state=state)  # type: ignore[call-arg]
        if not self.copyright_enabled.get():
            self.copyright_image = None
            self.copyright_path = ''
            self.copyright_map = None
            if self.copyright_rect:
                self.canvas.delete(self.copyright_rect)
                self.copyright_rect = None
        self.save_settings()

    def _mockups_effective_enabled(self):
        return self.pipeline_mode_var.get() != 'cliparts' and self.mockup_enabled.get()

    def on_pipeline_mode_changed(self, save=True):
        # In CLIPARTS mode we never generate mockups.
        if self.pipeline_mode_var.get() == 'cliparts':
            self.mockup_enabled_check.configure(state='disabled')  # type: ignore[call-arg]
        else:
            self.mockup_enabled_check.configure(state='normal')  # type: ignore[call-arg]

        self.toggle_mockup_settings()
        if save:
            self.save_settings()

    def on_rawprep_option_changed(self, save=True):
        # UI niceties: skip/delete zip only makes sense when unzip is on
        unzip_on = self.rawprep_unzip_var.get()
        state = 'normal' if unzip_on else 'disabled'
        self.rawprep_skip_check.configure(state=state)  # type: ignore[call-arg]
        self.rawprep_delete_zip_check.configure(state=state)  # type: ignore[call-arg]

        # delete-empty only makes sense if we flatten or unzip (because it targets extracted folders)
        del_ok = self.rawprep_delete_empty_var.get()
        _ = del_ok

        if save:
            self.save_settings()

    def run_all(self):
        if not self.project_folder:
            messagebox.showwarning("Varovani", "Prosim vyberte slozku projektu.")
            return

        # If Dry run is enabled, run only RAW prep (otherwise phase 2 would run on unchanged files).
        if self.rawprep_dry_run_var.get() and (self.rawprep_unzip_var.get() or self.rawprep_flatten_var.get() or self.rawprep_delete_empty_var.get()):
            self.run_raw_prep_only()
            return

        self._run_all_requested = True
        self.run_processing()

    def run_raw_prep_only(self):
        if not self.project_folder:
            messagebox.showwarning("Varovani", "Prosim vyberte slozku projektu.")
            return

        self.cancel_processing = False
        self.save_settings()

        t = threading.Thread(target=self._raw_prep_only_task)
        t.start()

    def _raw_prep_only_task(self):
        try:
            self.start_time = time.time()
            self.progress['value'] = 0
            self.progress_label.config(text="RAW prep...")
            stats = self._run_raw_prep()
            msg = f"RAW prep hotovo. Unzipped: {stats['unzipped']}, moved: {stats['moved']}, deleted_folders: {stats['folders_deleted']}, deleted_zips: {stats['zips_deleted']}"
            messagebox.showinfo("Hotovo", msg, parent=self.root)
        except Exception as e:
            logging.error(f"Chyba v RAW prep: {e}")
            messagebox.showerror("Chyba", f"RAW prep error: {e}")
        finally:
            self.progress['value'] = 0
            self.progress_label.config(text="")
            self.eta_label.config(text="")

    def _scan_raw_images(self):
        raw_folder = os.path.join(self.project_folder, 'RAW')
        if not os.path.exists(raw_folder):
            return []
        return [
            os.path.join(raw_folder, f)
            for f in os.listdir(raw_folder)
            if f.lower().endswith(VALID_EXTENSIONS)
        ]

    def _run_raw_prep(self):
        raw_root = Path(self.project_folder) / 'RAW'
        if not raw_root.exists():
            raise RuntimeError("Slozka 'RAW' nebyla nalezena ve vybrane slozce projektu.")

        dry_run = self.rawprep_dry_run_var.get()
        stats = {
            'unzipped': 0,
            'moved': 0,
            'folders_deleted': 0,
            'zips_deleted': 0,
        }

        def log(msg):
            logging.info(msg)
            self.progress_label.config(text=msg)
            self.root.update_idletasks()

        if self.rawprep_unzip_var.get():
            for zip_path in sorted(raw_root.glob('*.zip'), key=lambda p: p.name.lower()):
                if self.cancel_processing:
                    return stats
                dest = raw_root / zip_path.stem
                if dest.exists() and self.rawprep_skip_unzip_var.get():
                    log(f"RAW prep: skip unzip {zip_path.name} (folder exists)")
                    continue
                log(f"RAW prep: unzip {zip_path.name} -> {dest.name}")
                if not dry_run:
                    dest.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        zf.extractall(dest)
                stats['unzipped'] += 1

                if self.rawprep_delete_zip_var.get():
                    log(f"RAW prep: delete zip {zip_path.name}")
                    if not dry_run:
                        zip_path.unlink(missing_ok=True)
                    stats['zips_deleted'] += 1

        if self.rawprep_flatten_var.get():
            folders = sorted([p for p in raw_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
            for folder in folders:
                if self.cancel_processing:
                    return stats

                images = sorted(
                    [p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in VALID_EXTENSIONS],
                    key=lambda p: str(p).lower(),
                )
                if not images:
                    continue

                base = folder.name
                log(f"RAW prep: flatten {base} ({len(images)} images)")

                if dry_run:
                    idx = 1
                    for img in images:
                        ext = img.suffix
                        while (raw_root / f"{base}_{idx}{ext}").exists():
                            idx += 1
                        log(f"  would move: {img.name} -> {base}_{idx}{ext}")
                        idx += 1
                        stats['moved'] += 1
                    continue

                # 1) temp rename to avoid collisions
                temps = []
                for img in images:
                    tmp_name = f"__tmp__{uuid.uuid4().hex}{img.suffix}"
                    tmp_path = img.with_name(tmp_name)
                    img.rename(tmp_path)
                    temps.append(tmp_path)

                # 2) move to RAW root with "<folder>_<n>" names
                reserved = set()
                idx = 1
                for tmp_path in temps:
                    ext = tmp_path.suffix
                    while True:
                        name = f"{base}_{idx}{ext}"
                        if name.lower() in reserved:
                            idx += 1
                            continue
                        if not (raw_root / name).exists():
                            break
                        idx += 1
                    reserved.add(name.lower())
                    shutil.move(str(tmp_path), str(raw_root / name))
                    stats['moved'] += 1
                    idx += 1

        if self.rawprep_delete_empty_var.get():
            # Remove empty subdirs bottom-up and then top-level empty folders.
            for folder in sorted([p for p in raw_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
                if self.cancel_processing:
                    return stats
                self._delete_empty_dirs(folder, dry_run=dry_run)
                if not dry_run:
                    try:
                        next(folder.iterdir())
                    except StopIteration:
                        folder.rmdir()
                        stats['folders_deleted'] += 1
                    except FileNotFoundError:
                        # Folder was removed elsewhere; treat as deleted.
                        stats['folders_deleted'] += 1
                else:
                    # dry-run: report if empty
                    try:
                        next(folder.rglob('*'))
                    except (StopIteration, FileNotFoundError):
                        stats['folders_deleted'] += 1

        return stats

    def _delete_empty_dirs(self, root_folder: Path, dry_run=False):
        # Delete empty folders bottom-up.
        for dirpath, dirnames, filenames in os.walk(root_folder, topdown=False):
            p = Path(dirpath)
            # Do not remove the root folder itself here; caller decides.
            if p == root_folder:
                continue
            try:
                next(p.iterdir())
                continue
            except StopIteration:
                if dry_run:
                    continue
                try:
                    p.rmdir()
                except OSError:
                    pass

    def load_mockups(self):
        mockup_paths = filedialog.askopenfilenames(
            title="Vyberte mockupy",
            filetypes=[("Obrazky", "*.png;*.jpg;*.jpeg;*.webp")]
        )
        if mockup_paths:
            for mockup_path in mockup_paths:
                if mockup_path not in self.mockups:
                    self.mockups.append(mockup_path)
                    if mockup_path not in self.mockup_vars:
                        self.mockup_vars[mockup_path] = {'selected': tk.BooleanVar(value=True)}
            self.create_mockup_buttons()
            self.save_settings()
            messagebox.showinfo("Mockupy nacteny", f"{len(mockup_paths)} mockupu bylo uspesne nacteno.")

    def create_mockup_buttons(self):
        for widget in self.mockup_buttons_frame.winfo_children():
            widget.destroy()

        enabled = self._mockups_effective_enabled()

        for mockup_path in self.mockups:
            frame = tk.Frame(self.mockup_buttons_frame)
            frame.pack(fill=tk.X, pady=2)

            var = self.mockup_vars.get(mockup_path, {'selected': tk.BooleanVar(value=True)})['selected']
            self.mockup_vars[mockup_path] = {'selected': var}

            check = tk.Checkbutton(frame, variable=var, state='normal' if enabled else 'disabled')
            check.pack(side=tk.LEFT)

            mockup_name = os.path.splitext(os.path.basename(mockup_path))[0]
            button = tk.Button(frame, text=mockup_name, command=lambda path=mockup_path: self.show_mockup(path),
                               state='normal' if enabled else 'disabled')
            button.pack(side=tk.LEFT, padx=5)

            del_button = tk.Button(frame, text="X", fg="red", command=lambda path=mockup_path: self.delete_mockup(path),
                                   state='normal' if enabled else 'disabled')
            del_button.pack(side=tk.LEFT)

    def delete_mockup(self, mockup_path):
        if mockup_path in self.mockup_images:
            del self.mockup_images[mockup_path]
        if mockup_path in self.mockup_display_images:
            del self.mockup_display_images[mockup_path]
        if mockup_path in self.mockup_maps:
            del self.mockup_maps[mockup_path]
        if mockup_path in self.mockup_vars:
            del self.mockup_vars[mockup_path]
        if mockup_path in self.mockups:
            self.mockups.remove(mockup_path)

        self.create_mockup_buttons()
        self.canvas.delete("all")
        if self.current_mockup_path == mockup_path:
            self.current_mockup_path = None
        self.save_settings()

    def show_mockup(self, mockup_path):
        self.current_mockup_path = mockup_path

        if mockup_path not in self.mockup_images:
            try:
                mockup_image = Image.open(mockup_path)
                self.mockup_images[mockup_path] = mockup_image
                display_image = mockup_image.copy()
                display_image.thumbnail((self.canvas_width, self.canvas_height), resample=RESAMPLE_LANCZOS)  # type: ignore[arg-type]
                self.mockup_display_images[mockup_path] = display_image
            except Exception as e:
                logging.error(f"Chyba pri nacitani mockupu {mockup_path}: {e}")
                messagebox.showerror("Chyba", f"Nelze nacist mockup: {e}")
                return
        else:
            display_image = self.mockup_display_images[mockup_path]

        self.canvas_image = ImageTk.PhotoImage(display_image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.canvas_image)

        if mockup_path in self.mockup_maps:
            x1, y1, x2, y2 = self.mockup_maps[mockup_path]['display_coords']
            self.rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline='red')

        if self.copyright_enabled.get() and self.copyright_map:
            x1, y1, x2, y2 = self.copyright_map['display_coords']
            self.copyright_rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline='blue')

    def load_copyright_image(self):
        copyright_path = filedialog.askopenfilename(
            title="Vyberte Copyright obrazek",
            filetypes=[("Obrazky", "*.png;*.jpg;*.jpeg;*.webp")]
        )
        if copyright_path:
            try:
                self.copyright_image = Image.open(copyright_path)
                self.copyright_path = copyright_path
                messagebox.showinfo("Copyright nacten", "Nyni vyberte oblast pro Copyright na platne.")
                self.drawing_copyright_map = True
                if not self.current_mockup_path and self.mockups:
                    self.show_mockup(self.mockups[0])
            except Exception as e:
                logging.error(f"Chyba pri nacitani copyright obrazku {copyright_path}: {e}")
                messagebox.showerror("Chyba", f"Nelze nacist copyright obrazek: {e}")
            self.save_settings()

    def on_button_press(self, event):
        if self.current_mockup_path is None:
            return
        self.start_x = event.x
        self.start_y = event.y
        if self.drawing_copyright_map:
            if self.copyright_rect:
                self.canvas.delete(self.copyright_rect)
            self.copyright_rect = self.canvas.create_rectangle(
                self.start_x, self.start_y, self.start_x, self.start_y, outline='blue'
            )
        else:
            if self.rect:
                self.canvas.delete(self.rect)
            self.rect = self.canvas.create_rectangle(
                self.start_x, self.start_y, self.start_x, self.start_y, outline='red'
            )

    def on_move_press(self, event):
        if self.current_mockup_path is None:
            return
        curX, curY = (event.x, event.y)
        if self.drawing_copyright_map and self.copyright_rect:
            self.canvas.coords(self.copyright_rect, self.start_x, self.start_y, curX, curY)
        elif self.rect is not None:
            self.canvas.coords(self.rect, self.start_x, self.start_y, curX, curY)

    def on_button_release(self, event):
        if self.current_mockup_path is None:
            return
        if self.drawing_copyright_map and self.copyright_rect:
            display_coords = self.canvas.coords(self.copyright_rect)
            self.copyright_map = {'display_coords': display_coords}
            self.drawing_copyright_map = False
            self.save_settings()
        elif self.rect is not None:
            display_coords = self.canvas.coords(self.rect)
            self.mockup_maps[self.current_mockup_path] = {'display_coords': display_coords}
            self.save_settings()

    def open_settings_window(self):
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Nastaveni")
        settings_window.resizable(False, False)

        ttk.Label(settings_window, text="Limit velikosti ZIP archivu (MB):").grid(row=0, column=0, padx=10, pady=10)
        zip_limit_var = tk.DoubleVar(value=self.settings['zip_limit'] / (1024 * 1024))
        zip_limit_entry = ttk.Entry(settings_window, textvariable=zip_limit_var)
        zip_limit_entry.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(settings_window, text="Cesta ke spustitelnemu souboru Waifu2x (natvrdo):").grid(row=1, column=0, padx=10, pady=10)
        waifu2x_exe_var = tk.StringVar(value=WAIFU2X_EXE_FIXED)
        waifu2x_exe_entry = ttk.Entry(settings_window, textvariable=waifu2x_exe_var, state='disabled', width=60)
        waifu2x_exe_entry.grid(row=1, column=1, padx=10, pady=10, columnspan=2, sticky='we')

        ttk.Label(settings_window, text="Cesta k modelovemu adresari Waifu2x:").grid(row=2, column=0, padx=10, pady=10)
        model_dir_var = tk.StringVar(value=self.settings['model_dir'])
        model_dir_entry = ttk.Entry(settings_window, textvariable=model_dir_var)
        model_dir_entry.grid(row=2, column=1, padx=10, pady=10)
        ttk.Button(settings_window, text="Prochazet", command=lambda: self.browse_directory(model_dir_var)).grid(row=2, column=2, padx=5, pady=5)

        ttk.Label(settings_window, text="Celkova delka videa (sekundy):").grid(row=3, column=0, padx=10, pady=10)
        video_duration_var = tk.DoubleVar(value=self.settings.get('video_duration', 4.0))
        video_duration_entry = ttk.Entry(settings_window, textvariable=video_duration_var)
        video_duration_entry.grid(row=3, column=1, padx=10, pady=10)

        ttk.Label(settings_window, text="Upscale vystupni format:").grid(row=4, column=0, padx=10, pady=10)
        upscale_format_var = tk.StringVar(value=self.settings.get('upscale_output_format', 'png'))
        upscale_format_combo = ttk.Combobox(settings_window, textvariable=upscale_format_var, values=['png', 'jpg'], state='readonly', width=10)
        upscale_format_combo.grid(row=4, column=1, padx=10, pady=10, sticky='w')

        def save_and_close():
            try:
                self.settings['zip_limit'] = float(zip_limit_var.get()) * 1024 * 1024
                self.settings['model_dir'] = model_dir_var.get()
                video_duration = float(video_duration_var.get())
                if video_duration <= 0:
                    raise ValueError("Delka videa musi byt vetsi nez 0.")
                self.settings['video_duration'] = video_duration
                self.settings['upscale_output_format'] = upscale_format_var.get() or 'png'
                # Keep main window checkbox in sync if already created.
                if hasattr(self, 'upscale_output_png_var'):
                    self.upscale_output_png_var.set(self.settings['upscale_output_format'] == 'png')
                self.save_settings()
                settings_window.destroy()
            except ValueError as e:
                messagebox.showerror("Chyba", f"Prosim zadejte platne hodnoty v nastaveni: {e}")

        ttk.Button(settings_window, text="Ulozit", command=save_and_close).grid(row=5, column=0, columnspan=3, pady=10)

    def browse_file(self, var):
        file_path = filedialog.askopenfilename(title="Vyberte soubor")
        if file_path:
            var.set(file_path)

    def browse_directory(self, var):
        dir_path = filedialog.askdirectory(title="Vyberte slozku")
        if dir_path:
            var.set(dir_path)

    def select_project_folder(self):
        folder_path = filedialog.askdirectory(title='Vyberte slozku projektu')
        if folder_path:
            self.project_folder = folder_path
            self.project_label.config(text=f"Slozka projektu: {self.project_folder}")
            raw_folder = os.path.join(self.project_folder, 'RAW')
            if not os.path.exists(raw_folder):
                messagebox.showwarning("Varovani", "Slozka 'RAW' nebyla nalezena ve vybrane slozce projektu.")
                return
            self.image_paths = [
                os.path.join(raw_folder, f)
                for f in os.listdir(raw_folder)
                if f.lower().endswith(VALID_EXTENSIONS)
            ]
            if self.image_paths:
                logging.info(f"Nacteno {len(self.image_paths)} obrazku ze slozky 'RAW'.")
            else:
                logging.warning("Ve slozce 'RAW' nebyly nalezeny zadne obrazky.")
            self.save_settings()

    def select_images_for_brightening(self):
        if not self.project_folder:
            messagebox.showwarning("Varovani", "Nejdrive vyberte slozku projektu.")
            return
        raw_folder = os.path.join(self.project_folder, 'RAW')
        if not os.path.exists(raw_folder):
            messagebox.showwarning("Varovani", "Slozka 'RAW' neexistuje ve vybrane slozce projektu.")
            return
        selected_files = filedialog.askopenfilenames(title='Vyberte obrazky pro vybelit 2x', initialdir=raw_folder, filetypes=[
            ("Obrazky", "*.png;*.jpg;*.jpeg;*.bmp;*.tiff;*.webp")
        ])
        if selected_files:
            self.selected_images_for_brightening = [os.path.splitext(os.path.basename(f))[0] for f in selected_files]
            self.save_settings()

    def run_processing(self):
        if not self.project_folder:
            messagebox.showwarning("Varovani", "Prosim vyberte slozku projektu.")
            return

        self.author_name = self.author_entry.get()
        if not self.author_name:
            messagebox.showwarning("Varovani", "Prosim zadejte jmeno autora.")
            return

        if self._mockups_effective_enabled():
            for mockup_path in self.mockups:
                if self.mockup_vars.get(mockup_path, {}).get('selected', False) and mockup_path not in self.mockup_maps:
                    mockup_name = os.path.splitext(os.path.basename(mockup_path))[0]
                    messagebox.showwarning("Chybejici mapa", f"Pro mockup '{mockup_name}' neni nastavena oblast pro navrh.")
                    return
            if self.copyright_enabled.get() and not self.copyright_image:
                messagebox.showwarning("Chybejici Copyright", "Nejdrive vyberte obrazek pro Copyright.")
                return
            if self.copyright_enabled.get() and not self.copyright_map:
                messagebox.showwarning("Chybejici mapa pro Copyright", "Nejdrive nastavte oblast pro Copyright.")
                return

        self.cancel_processing = False
        self.save_settings()
        processing_thread = threading.Thread(target=self.processing_task)
        processing_thread.start()

    def cancel_processing_task(self):
        self.cancel_processing = True
        logging.info("Zpracovani bylo uzivatelem zruseno.")
        self.progress_label.config(text="Zpracovani bylo zruseno.")
        messagebox.showinfo("Zruseno", "Zpracovani bylo zruseno uzivatelem.")

    def processing_task(self):
        try:
            # Optional Phase 1 (RAW prep) before the main pipeline
            if self._run_all_requested:
                self.progress_label.config(text="RAW prep...")
                self.root.update_idletasks()
                self._run_raw_prep()
                if self.cancel_processing:
                    return
                if self.rawprep_dry_run_var.get():
                    # Do not continue to phase 2 on dry-run.
                    messagebox.showinfo("Hotovo", "RAW prep dry-run dokonceny (zadne zmeny nebyly provedeny).", parent=self.root)
                    return

            # Always rescan RAW root before upscaling
            self.image_paths = self._scan_raw_images()
            if not self.image_paths:
                messagebox.showwarning("Varovani", "Ve slozce 'RAW' nejsou zadne obrazky v rootu. (Mozna jsou stale ve slozkach?)")
                return

            upscale_dir = os.path.join(self.project_folder, "upscale")
            if os.path.exists(upscale_dir) and os.listdir(upscale_dir):
                skip_upscaling = True
                logging.info("Slozka 'upscale' jiz existuje a obsahuje obrazky. Preskakuji upscalovani.")
            else:
                skip_upscaling = False

            self.start_time = time.time()

            if not skip_upscaling:
                self.upscale_images()
                if self.cancel_processing:
                    return

            self.process_upscaled_images()
            if self.cancel_processing:
                return

            subfolder_names, naming_style = self.create_subfolders_in_lightroom_folders(self.project_folder, self.author_name)
            self.naming_style = naming_style
            if self.cancel_processing:
                return

            self.distribute_images(self.project_folder, ["lightroom", "lightroom watermark"], subfolder_names, naming_style)
            if self.cancel_processing:
                return

            if self._mockups_effective_enabled():
                self.generate_mockups(subfolder_names)
                if self.cancel_processing:
                    return

            self.process_folders(self.project_folder, subfolder_names)
            if self.cancel_processing:
                return

            messagebox.showinfo("Dokonceno", "Obrazky a mockupy byly zpracovany.", parent=self.root)
            self.progress['value'] = 0
            self.progress_label.config(text="")
            self.eta_label.config(text="")
        except Exception as e:
            logging.error(f"Chyba pri zpracovani: {e}")
            messagebox.showerror("Chyba", f"Nastala chyba pri zpracovani: {e}")
        finally:
            self._run_all_requested = False

    def upscale_images(self):
        # Use RealESRGAN "3D Real-life" style for sharper results.
        realesrgan_exe = REALESRGAN_EXE_FIXED
        realesrgan_model_dir = REALESRGAN_MODEL_DIR_FIXED
        realesrgan_model_name = REALESRGAN_MODEL_NAME_FIXED

        if not realesrgan_exe or not os.path.exists(realesrgan_exe):
            messagebox.showerror("Chyba", f"Spustitelny soubor RealESRGAN nebyl nalezen na {realesrgan_exe}")
            return
        if not os.path.exists(realesrgan_model_dir):
            messagebox.showerror("Chyba", f"Modely RealESRGAN nebyly nalezeny v {realesrgan_model_dir}")
            return

        upscale_output_dir = os.path.join(self.project_folder, "upscale")
        os.makedirs(upscale_output_dir, exist_ok=True)

        output_fmt = 'png' if self.upscale_output_png_var.get() else 'jpg'
        output_ext = FormatPolicy.output_ext_for_choice(output_fmt)
        jpeg_quality = int(self.settings.get('upscale_jpeg_quality', 100) or 100)

        total_images = len(self.image_paths)
        self.progress['maximum'] = total_images
        self.progress['value'] = 0

        try:
            self.scale_factor = int(self.scale_entry.get())
            if self.scale_factor not in [2, 3, 4]:
                messagebox.showerror("Chyba", "RealESRGAN podporuje zvetseni 2x, 3x nebo 4x. Doporuceno: 4x (3D Real-life).")
                return
        except ValueError:
            messagebox.showerror("Chyba", "Prosim zadejte platny pocet zvetseni (2/3/4).")
            return

        for idx, img_path in enumerate(self.image_paths, 1):
            if self.cancel_processing:
                break
            base_name = os.path.splitext(os.path.basename(img_path))[0]
            input_ext = os.path.splitext(img_path)[1].lower()
            output_filename = f"{base_name}{output_ext}"
            output_path = os.path.join(upscale_output_dir, output_filename)

            # For JPG output, run RealESRGAN to PNG first (lossless), then convert once.
            tmp_output_path = output_path
            tmp_ext = output_ext
            if output_ext == '.jpg':
                tmp_ext = '.png'
                tmp_output_path = os.path.join(upscale_output_dir, f"{base_name}{tmp_ext}")

            command = [
                realesrgan_exe,
                '-i', img_path,
                '-o', tmp_output_path,
                '-s', str(self.scale_factor),
                '-t', '0',
                '-m', realesrgan_model_dir,
                '-n', realesrgan_model_name,
                '-x',
                '-f', 'png',
            ]

            try:
                subprocess.run(command, check=True)
                logging.info(f"Upscalovan obrazek {img_path} na {tmp_output_path}")

                # If desired output is PNG, preserve alpha (for transparent sources)
                if output_ext == '.png' and input_ext == '.png':
                    try:
                        src = Image.open(img_path).convert('RGBA')
                        alpha = src.split()[-1]
                        out_img = Image.open(tmp_output_path).convert('RGBA')
                        alpha_resized = alpha.resize(out_img.size, RESAMPLE_LANCZOS)
                        out_img.putalpha(alpha_resized)
                        out_img.save(tmp_output_path, format='PNG')
                    except Exception as e:
                        logging.warning(f"Nepodarilo se zachovat alpha kanal pro {img_path}: {e}")

                # If desired output is JPG, convert from upscaled PNG once (no double-JPEG)
                if output_ext == '.jpg':
                    try:
                        out_img = Image.open(tmp_output_path).convert('RGBA')
                        # Flatten on white background if alpha exists
                        bg = Image.new('RGB', out_img.size, (255, 255, 255))
                        bg.paste(out_img, mask=out_img.split()[-1])
                        bg.save(output_path, format='JPEG', quality=jpeg_quality, dpi=(300, 300))
                        try:
                            os.remove(tmp_output_path)
                        except OSError:
                            pass
                        logging.info(f"Preveden upscale vystup do JPG: {output_path}")
                    except Exception as e:
                        logging.error(f"Nepodarilo se prevest {tmp_output_path} do JPG: {e}")
                        continue

                # Brightening is optional; only apply when user enables it.
                if self.brighten_twice_var.get():
                    # First pass for all images
                    self.enhance_image(output_path, output_ext)
                    # Optional second pass for selected images (or all if none selected)
                    if not self.selected_images_for_brightening or base_name in self.selected_images_for_brightening:
                        self.enhance_image(output_path, output_ext)
            except subprocess.CalledProcessError as e:
                logging.error(f"Chyba pri upscalovani {img_path}: {e}")
                continue

            self.progress['value'] = idx
            elapsed_time = time.time() - self.start_time
            avg_time_per_image = elapsed_time / idx
            remaining_images = total_images - idx
            eta = avg_time_per_image * remaining_images
            self.progress_label.config(text=f"Upscalovani obrazku {idx}/{total_images}")
            self.eta_label.config(text=f"Odhadovany cas dokonceni: {int(eta)} sekund")
            self.root.update_idletasks()

    def enhance_image(self, output_path, output_ext):
        try:
            img = Image.open(output_path)
            enhancer = ImageEnhance.Brightness(img)
            enhanced_img = enhancer.enhance(1.1)
            FormatPolicy.save_enhanced(enhanced_img, output_path, output_ext)
        except Exception as e:
            logging.error(f"Chyba pri zlepsovani obrazku {output_path}: {e}")
            self.progress_label.config(text=f"Chyba pri zlepsovani obrazku {output_path}: {e}")

    def process_one_image(self, filename, upscale_dir, lightroom_dir, watermark_dir, font_path):
        if self.cancel_processing:
            return

        try:
            img_path = os.path.join(upscale_dir, filename)
            img = Image.open(img_path)
            input_ext = os.path.splitext(filename)[1].lower()

            lightroom_img = img.copy()
            lightroom_output_path = os.path.join(lightroom_dir, os.path.splitext(filename)[0] + input_ext)
            FormatPolicy.save_lightroom(lightroom_img, lightroom_output_path, input_ext)

            watermark_img = FormatPolicy.prepare_for_watermark(img.copy(), input_ext)
            txt_layer = Image.new('RGBA', watermark_img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_layer)

            img_width, img_height = watermark_img.size
            margin = img_width / 20
            max_text_width = img_width - 2 * margin

            font_size = 100
            while True:
                font = ImageFont.truetype(font_path, size=font_size)
                bbox = draw.textbbox((0, 0), self.author_name, font=font)
                text_width = bbox[2] - bbox[0]
                if text_width <= max_text_width / 4:
                    break
                font_size -= 1

            font_size *= 4
            font = ImageFont.truetype(font_path, size=font_size)
            bbox = draw.textbbox((0, 0), self.author_name, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            text_x = (img_width - text_width) / 2
            text_y = (img_height - text_height) / 2

            shadow_color = (0, 0, 0, int(255 * 0.3))
            shadow_offset = (5, 5)
            draw.text(
                (text_x + shadow_offset[0], text_y + shadow_offset[1]),
                self.author_name,
                font=font,
                fill=shadow_color
            )

            text_color = (255, 255, 255, int(255 * 0.5))
            draw.text(
                (text_x, text_y),
                self.author_name,
                font=font,
                fill=text_color
            )

            combined = Image.alpha_composite(watermark_img, txt_layer)
            combined = combined.convert('RGB')
            combined.save(
                os.path.join(watermark_dir, os.path.splitext(filename)[0] + '.jpg'),
                format='JPEG',
                quality=50,
                dpi=(300, 300)
            )

        except Exception as e:
            logging.error(f"Chyba pri zpracovani {filename}: {e}")

    def process_upscaled_images(self):
        upscale_dir = os.path.join(self.project_folder, "upscale")
        if not os.path.exists(upscale_dir):
            messagebox.showerror("Chyba", "Slozka 'upscale' nebyla nalezena.")
            return

        lightroom_dir = os.path.join(self.project_folder, "lightroom")
        watermark_dir = os.path.join(self.project_folder, "lightroom watermark")
        os.makedirs(lightroom_dir, exist_ok=True)
        os.makedirs(watermark_dir, exist_ok=True)

        font_path = find_baskerville_font()
        if not font_path:
            messagebox.showerror(
                "Chyba",
                "Font 'Baskerville Old Face' (BASKVILL.TTF) nebyl nalezen ani v C:\\Windows\\Fonts, ani v uzivatelskych Microsoft\\Windows\\Fonts.\nNainstalujte ho pro vsechny uzivatele nebo vlozte soubor .ttf do stejne slozky jako tento skript."
            )
            return

        images = [f for f in os.listdir(upscale_dir) if f.lower().endswith(('.jpg', '.png'))]
        total_images = len(images)
        self.progress['maximum'] = total_images
        self.progress['value'] = 0

        max_workers = min(8, os.cpu_count() or 1)
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self.process_one_image, filename, upscale_dir, lightroom_dir, watermark_dir, font_path)
                for filename in images
            ]
            for _ in as_completed(futures):
                if self.cancel_processing:
                    break
                completed += 1
                elapsed_time = time.time() - self.start_time
                avg_time = elapsed_time / completed if completed > 0 else 1
                eta = avg_time * (total_images - completed)
                self.progress['value'] = completed
                self.progress_label.config(text=f"Zpracovani obrazku {completed}/{total_images}")
                self.eta_label.config(text=f"Odhadovany cas dokonceni: {int(eta)} sekund")
                self.root.update_idletasks()

    def generate_mockups(self, subfolder_names):
        logging.info("Spoustim generovani mockupu.")
        upscale_dir = os.path.join(self.project_folder, "upscale")
        if not os.path.exists(upscale_dir):
            logging.error("Slozka 'upscale' neexistuje, mockupy se negeneruji.")
            messagebox.showwarning("Varovani", "Slozka 'upscale' neexistuje, mockupy nebudou generovany.")
            return

        design_paths = [os.path.join(upscale_dir, f) for f in os.listdir(upscale_dir)
                        if f.lower().endswith(('.jpg', '.png'))]
        if not design_paths:
            logging.error("Zadne designy nebyly nalezeny ve slozce 'upscale', mockupy se negeneruji.")
            messagebox.showwarning("Varovani", "Zadne designy nebyly nalezeny ve slozce 'upscale', mockupy nebudou generovany.")
            return

        design_images = {}
        for design_path in design_paths:
            try:
                design_image = Image.open(design_path)
                design_name = os.path.splitext(os.path.basename(design_path))[0]
                design_images[design_name] = design_image
                logging.info(f"Nacten design: {design_path}")
            except Exception as e:
                logging.error(f"Chyba pri nacitani designu {design_path}: {e}")
                continue

        if not design_images:
            logging.error("Zadne platne designy nebyly nacteny, mockupy se negeneruji.")
            messagebox.showwarning("Varovani", "Zadne platne designy nebyly nacteny, mockupy nebudou generovany.")
            return

        watermark_dir = os.path.join(self.project_folder, "lightroom watermark")
        total_steps = len(subfolder_names)
        current_step = 0

        for subfolder_name in subfolder_names:
            if self.cancel_processing:
                logging.info("Generovani mockupu zruseno uzivatelem.")
                break
            target_dir = os.path.join(watermark_dir, subfolder_name)
            os.makedirs(target_dir, exist_ok=True)
            logging.info(f"Zpracovavam podslozku: {target_dir}")

            design_name = subfolder_name.replace(f" {self.author_name}", "")
            logging.info(f"Hledam design odpovidajici nazvu: {design_name}")

            if design_name not in design_images:
                logging.warning(f"Design '{design_name}' nebyl nalezen ve slozce 'upscale', preskakuji podslozku {subfolder_name}.")
                continue

            design_image = design_images[design_name]
            logging.info(f"Nacten design '{design_name}' pro podslozku {subfolder_name}")

            for mockup_path in self.mockups:
                if not self.mockup_vars.get(mockup_path, {}).get('selected', False):
                    logging.info(f"Mockup {mockup_path} neni vybran, preskakuji.")
                    continue
                mockup_image = self.mockup_images.get(mockup_path)
                display_image = self.mockup_display_images.get(mockup_path)
                map_info = self.mockup_maps.get(mockup_path)
                if not all([mockup_image, display_image, map_info]):
                    logging.error(f"Chybi data pro mockup {mockup_path}: "
                                  f"mockup_image={bool(mockup_image)}, "
                                  f"display_image={bool(display_image)}, "
                                  f"map_info={bool(map_info)}. Preskakuji.")
                    continue
                assert mockup_image is not None
                assert display_image is not None
                assert map_info is not None
                display_coords = map_info['display_coords']
                logging.info(f"Zpracovavam mockup {mockup_path} s designem {design_name}")

                ratio_x = mockup_image.width / display_image.width
                ratio_y = mockup_image.height / display_image.height
                x1, y1, x2, y2 = display_coords
                x1_full = int(x1 * ratio_x)
                y1_full = int(y1 * ratio_y)
                x2_full = int(x2 * ratio_x)
                y2_full = int(y2 * ratio_y)
                area_width = x2_full - x1_full
                area_height = y2_full - y1_full

                design_ratio = design_image.width / design_image.height
                new_width = area_width
                new_height = int(new_width / design_ratio)
                if new_height > area_height:
                    new_height = area_height
                    new_width = int(new_height * design_ratio)
                resized_design = design_image.resize((new_width, new_height), RESAMPLE_LANCZOS)

                mockup_copy = mockup_image.copy()
                resized_design = resized_design.convert("RGBA")
                paste_x = x1_full + (area_width - new_width) // 2
                paste_y = y1_full + (area_height - new_height) // 2
                mockup_copy.paste(resized_design, (paste_x, paste_y), resized_design)

                if self.copyright_enabled.get() and self.copyright_image and self.copyright_map:
                    assert self.copyright_image is not None
                    assert self.copyright_map is not None
                    display_coords_c = self.copyright_map['display_coords']
                    x1_c, y1_c, x2_c, y2_c = display_coords_c
                    x1_full_c = int(x1_c * ratio_x)
                    y1_full_c = int(y1_c * ratio_y)
                    x2_full_c = int(x2_c * ratio_x)
                    y2_full_c = int(y2_c * ratio_y)
                    area_width_c = x2_full_c - x1_full_c
                    area_height_c = y2_full_c - y1_full_c

                    copy_ratio = self.copyright_image.width / self.copyright_image.height
                    new_width_c = area_width_c
                    new_height_c = int(new_width_c / copy_ratio)
                    if new_height_c > area_height_c:
                        new_height_c = area_height_c
                        new_width_c = int(new_height_c * copy_ratio)
                    resized_copy = self.copyright_image.resize((new_width_c, new_height_c), RESAMPLE_LANCZOS)

                    resized_copy = resized_copy.convert("RGBA")

                    mockup_width = mockup_image.width
                    mockup_height = mockup_image.height

                    distances = {}
                    distances['tl'] = sqrt((x1_full_c - 0) ** 2 + (y1_full_c - 0) ** 2)
                    distances['tr'] = sqrt((x2_full_c - mockup_width) ** 2 + (y1_full_c - 0) ** 2)
                    distances['bl'] = sqrt((x1_full_c - 0) ** 2 + (y2_full_c - mockup_height) ** 2)
                    distances['br'] = sqrt((x2_full_c - mockup_width) ** 2 + (y2_full_c - mockup_height) ** 2)

                    closest_corner = min(distances, key=lambda k: distances[k])

                    if closest_corner == 'tl':
                        paste_x_c = x1_full_c
                        paste_y_c = y1_full_c
                    elif closest_corner == 'tr':
                        paste_x_c = x2_full_c - new_width_c
                        paste_y_c = y1_full_c
                    elif closest_corner == 'bl':
                        paste_x_c = x1_full_c
                        paste_y_c = y2_full_c - new_height_c
                    else:
                        paste_x_c = x2_full_c - new_width_c
                        paste_y_c = y2_full_c - new_height_c

                    mockup_copy.paste(resized_copy, (paste_x_c, paste_y_c), resized_copy)
                    logging.info(f"Pridan copyright na mockup {mockup_path}")

                mockup_name = os.path.splitext(os.path.basename(mockup_path))[0]
                output_file = os.path.join(
                    target_dir, f"{design_name}_na_{mockup_name}.jpg"
                )
                mockup_copy.save(output_file, "JPEG", quality=50, dpi=(300, 300))
                logging.info(f"Vygenerovan mockup: {output_file}")

            current_step += 1
            self.update_progress(current_step, total_steps, f"Generovani mockupu ve slozce {subfolder_name}")

    def create_subfolders_in_lightroom_folders(self, base_path, author_name):
        lightroom_path = Path(base_path) / "lightroom"
        stems = [image.stem for image in lightroom_path.iterdir() if image.is_file()]
        if self.pipeline_mode_var.get() == 'designs_transparent':
            naming_style = 'designs_transparent'
            subfolder_names = set(stems)
        else:
            naming_style = NamingStrategy.detect_style(stems)
            subfolder_names = set()
            for stem in stems:
                group_name = NamingStrategy.group_name(stem, naming_style)
                if group_name:
                    subfolder_names.add(group_name)

        subfolder_names = [f"{name} {author_name}" for name in subfolder_names]

        for main_folder in ["lightroom", "lightroom watermark"]:
            for subfolder_name in subfolder_names:
                subfolder_path = Path(base_path) / main_folder / subfolder_name
                subfolder_path.mkdir(parents=True, exist_ok=True)

        return subfolder_names, naming_style

    def distribute_images(self, base_path, main_folders, subfolder_names, naming_style=None):
        for main_folder in main_folders:
            main_folder_path = Path(base_path) / main_folder
            for image in main_folder_path.iterdir():
                if image.is_file():
                    if self.pipeline_mode_var.get() == 'designs_transparent':
                        group_name = image.stem
                    else:
                        group_name = NamingStrategy.group_name(image.stem, naming_style or 'mixed')
                    target_subfolder = f"{group_name} {self.author_name}"
                    if target_subfolder in subfolder_names:
                        target_folder_path = main_folder_path / target_subfolder
                        try:
                            shutil.move(str(image), str(target_folder_path / image.name))
                            logging.info(f"Presunut soubor {image} do {target_folder_path}")
                        except Exception as e:
                            logging.error(f"Chyba pri presunu souboru {image}: {e}")

    def process_folders(self, base_path, subfolder_names):
        total_steps = len(subfolder_names) * 3
        if self.create_video_var.get():
            total_steps += len(subfolder_names)
        if self._mockups_effective_enabled():
            total_steps += len(subfolder_names)
        current_step = 0

        for subfolder_name in subfolder_names:
            if self.cancel_processing:
                break

            lightroom_path = Path(base_path) / "lightroom" / subfolder_name
            watermark_path = Path(base_path) / "lightroom watermark" / subfolder_name

            self.rename_files_in_folder(lightroom_path, subfolder_name)
            current_step += 1
            self.update_progress(current_step, total_steps, f"Prejmenovavani souboru ve slozce {subfolder_name}")

            self.compress_files_with_limit(lightroom_path, subfolder_name, self.settings['zip_limit'])
            current_step += 1
            self.update_progress(current_step, total_steps, f"Komprimovani souboru ve slozce {subfolder_name}")

            self.rename_files_in_folder(watermark_path, subfolder_name)
            current_step += 1
            self.update_progress(current_step, total_steps, f"Prejmenovavani watermark ve slozce {subfolder_name}")

            if self.create_video_var.get():
                self.create_video_from_images(watermark_path)
                current_step += 1
                self.update_progress(current_step, total_steps, f"Vytvareni videa ve slozce {subfolder_name}")

    def rename_files_in_folder(self, folder_path, subfolder_name):
        files = sorted(folder_path.iterdir())
        for i, file in enumerate(files):
            if file.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                new_filename = f"{subfolder_name}_{i + 1}{file.suffix}"
                new_path = folder_path / new_filename
                try:
                    file.rename(new_path)
                    logging.info(f"Prejmenovan {file} na {new_path}")
                except Exception as e:
                    logging.error(f"Chyba pri prejmenovani {file}: {e}")

    def compress_files_with_limit(self, folder_path, subfolder_name, limit):
        all_files = [f for f in folder_path.iterdir() if f.suffix.lower() in ['.jpg', '.jpeg', '.png']]
        if not all_files:
            return
        zip_counter = 1
        zip_size = 0
        zip_name = f"{subfolder_name}_archive_{zip_counter}.zip"
        zipf = zipfile.ZipFile(folder_path / zip_name, 'w', zipfile.ZIP_DEFLATED)
        try:
            for file in all_files:
                if self.cancel_processing:
                    break
                file_size = file.stat().st_size
                if zip_size + file_size > limit:
                    zipf.close()
                    zip_counter += 1
                    zip_name = f"{subfolder_name}_archive_{zip_counter}.zip"
                    zipf = zipfile.ZipFile(folder_path / zip_name, 'w', zipfile.ZIP_DEFLATED)
                    zip_size = 0
                zipf.write(file, arcname=file.name)
                zip_size += file_size
            zipf.close()
        except Exception as e:
            logging.error(f"Chyba pri kompresi souboru ve slozce {folder_path}: {e}")

    def create_video_from_images(self, images_folder):
        if self.cancel_processing:
            return

        error_log_path = images_folder / "error_log.txt"

        def log_error(message):
            with open(error_log_path, "a", encoding="utf-8") as log_file:
                log_file.write(message + "\n")
            logging.error(message)

        try:
            folder_name = images_folder.name
            video_name = f"{folder_name}.mp4"

            images = [img for img in images_folder.iterdir() if img.suffix.lower() in (".jpg", ".jpeg", ".png")]
            total_images = len(images)
            if not images:
                log_error(f"Ve slozce {images_folder} nejsou zadne obrazky.")
                return

            images.sort()
            image_sequence = []
            target_size = None
            target_ratio = None

            for img_path in images:
                try:
                    img = Image.open(img_path).convert("RGB")
                    target_size = img.size
                    target_ratio = img.width / img.height
                    logging.info(f"Prvni obrazek {img_path} urcil cilovou velikost: {target_size}, pomer stran: {target_ratio:.2f}")
                    image_sequence.append(np.array(img))
                    break
                except UnidentifiedImageError:
                    log_error(f"Soubor {img_path} neni platny obrazek a byl preskocen.")
                except Exception as e:
                    log_error(f"Nastala chyba pri nacitani prvniho obrazku {img_path}: {e}")

            if not target_size:
                log_error(f"Zadny platny prvni obrazek nebyl nalezen ve slozce {images_folder}, pouzije se vychozi velikost.")
                target_size = (1920, 1080)
                target_ratio = 1920 / 1080

            skipped_images = []
            for img_path in images[1:]:
                if self.cancel_processing:
                    break
                try:
                    img = Image.open(img_path).convert("RGB")
                    img_ratio = img.width / img.height

                    if img_ratio > target_ratio:
                        new_height = target_size[1]
                        new_width = int(new_height * img_ratio)
                    else:
                        new_width = target_size[0]
                        new_height = int(new_width / img_ratio)

                    img = img.resize((new_width, new_height), RESAMPLE_LANCZOS)

                    left = (new_width - target_size[0]) // 2
                    top = (new_height - target_size[1]) // 2
                    img = img.crop((left, top, left + target_size[0], top + target_size[1]))

                    image_sequence.append(np.array(img))
                    logging.info(f"Zpracovan obrazek {img_path} pro video, velikost: {img.size}")
                except UnidentifiedImageError:
                    log_error(f"Soubor {img_path} neni platny obrazek a byl preskocen.")
                    skipped_images.append(img_path.name)
                except Exception as e:
                    log_error(f"Nastala chyba pri nacitani obrazku {img_path}: {e}")
                    skipped_images.append(img_path.name)

            if not image_sequence:
                log_error(f"Zadne obrazky nebyly nacteny ve slozce {images_folder}, video nelze vytvorit.")
                messagebox.showwarning("Varovani", f"Zadne platne obrazky nebyly nacteny ve slozce {images_folder}. Video nebylo vytvoreno.")
                return

            num_images = len(image_sequence)
            if num_images < total_images:
                skipped_count = total_images - num_images
                warning_msg = (f"Varovani: Ve slozce {images_folder} bylo nalezeno {total_images} obrazku, "
                               f"ale pouze {num_images} bylo nacteno do videa. "
                               f"Preskoceno {skipped_count} obrazku: {', '.join(skipped_images)}")
                log_error(warning_msg)
                messagebox.showwarning("Varovani", warning_msg)

            total_duration = self.settings['video_duration']
            duration_per_image = total_duration / num_images if num_images > 0 else 1.0
            fps = max(1, min(30, int(num_images / total_duration)))

            logging.info(f"Vytvarim video s {num_images} obrazky, doba zobrazeni na obrazek: {duration_per_image:.2f}s, FPS: {fps}")

            if self.cancel_processing:
                return
            try:
                clip = ImageSequenceClip(image_sequence, durations=[duration_per_image] * num_images)
                video_path = images_folder / video_name
                clip.write_videofile(str(video_path), fps=fps, codec="libx264", audio=False)
                logging.info(f"Video bylo uspesne vytvoreno a ulozeno jako {video_path}")
            except Exception as e:
                log_error(f"Nastala chyba pri vytvareni videa ve slozce {images_folder}: {e}")
                messagebox.showerror("Chyba", f"Chyba pri vytvareni videa ve slozce {images_folder}: {e}")

        except Exception as e:
            log_error(f"Doslo k neocekavane chybe ve slozce {images_folder}: {e}")
            messagebox.showerror("Chyba", f"Neocekavana chyba pri vytvareni videa ve slozce {images_folder}: {e}")

    def update_progress(self, current_step, total_steps, message):
        progress_percentage = (current_step / total_steps) * 100
        self.progress['value'] = progress_percentage
        elapsed_time = time.time() - self.start_time
        avg_time_per_step = elapsed_time / current_step if current_step > 0 else 1
        remaining_steps = total_steps - current_step
        eta = avg_time_per_step * remaining_steps
        self.progress_label.config(text=message)
        self.eta_label.config(text=f"Odhadovany cas dokonceni: {int(eta)} sekund")
        self.root.update_idletasks()

    def open_project_folder(self):
        if self.project_folder:
            try:
                os.startfile(self.project_folder)
            except Exception as e:
                messagebox.showerror("Chyba", f"Nelze otevrit slozku: {e}")
        else:
            messagebox.showinfo("Info", "Nejdrive vyberte slozku projektu.")


def main():
    root = tk.Tk()
    app = ImageProcessingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
