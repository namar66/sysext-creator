#!/usr/bin/python3

import sys
import os
import subprocess
import logging
import re
import shutil
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QSplitter, QListWidget, QTableView,
                             QLineEdit, QTabWidget, QTextEdit, QLabel, QPushButton,
                             QHeaderView, QMenu, QMessageBox, QAbstractItemView,
                             QDialog, QProgressBar, QInputDialog, QTextBrowser, QMenuBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QTimer
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction, QIcon, QPixmap

# Logging configuration for debugging and background monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ==========================================
# GLOBAL CONFIGURATION
# ==========================================
CACHE_DIR = os.path.expanduser("~/.cache/sysext-creator")
EXTENSIONS_DIR = "/var/lib/extensions"
MANIFEST_DIR = "/usr/share/sysext/manifests"

# ==========================================
# BACKGROUND WORKER: TOOLBOX REBUILD
# ==========================================
class ToolboxRebuildWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            self.log_output.emit("Removing old 'sysext-builder' container...")
            subprocess.run(["toolbox", "rm", "-f", "sysext-builder"], capture_output=True)

            self.log_output.emit("Creating fresh 'sysext-builder' container matching host OS...")
            self.log_output.emit("(This will download the new base image, please be patient.)")

            res = subprocess.run(["toolbox", "create", "-c", "sysext-builder"], capture_output=True, text=True)

            if res.returncode == 0:
                self.finished.emit(True, "✅ Container successfully rebuilt for the new OS version.")
            else:
                self.finished.emit(False, f"❌ Failed to create container: {res.stderr}")
        except Exception as e:
            self.finished.emit(False, str(e))

# ==========================================
# UI DIALOGS: HELP & ABOUT
# ==========================================
class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 How to Use Sysext Creator Pro")
        self.resize(650, 500)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("""
        <h2>Welcome to Sysext Creator Pro</h2>
        <p>This tool securely builds and manages systemd-sysext layered images for Fedora Atomic.</p>

        <h3>1. Searching & Queueing</h3>
        <p>Use the <b>Available (DNF)</b> tab to search the Fedora repositories. Select the packages you need, right-click, and add them to the <b>Transaction Queue</b>.</p>

        <h3>2. Building an Extension</h3>
        <p>Once you have your packages in the queue, click <b>Process Transaction</b>. The builder will use a background Toolbox container to safely download and compress the files into an EROFS image.</p>

        <h3>3. Management & Diagnostics</h3>
        <p>Go to the <b>Installed</b> tab to view or remove active extensions. If your system behaves weirdly, use the <b>System Doctor</b> tab to scan for RPM file conflicts or /etc symlink overrides.</p>

        <p><i>Note: Removing or deploying an extension requires root privileges via Polkit.</i></p>
        """)
        layout.addWidget(browser)
        btn = QPushButton("Got it!")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ℹ️ About")
        self.setFixedSize(480, 200) # Slightly larger breathing room
        layout = QHBoxLayout(self)

        icon_label = QLabel()
        icon_path = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/sysext-creator.png")
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pix)
        else:
            icon_label.setText("No Icon") # Fallback
        layout.addWidget(icon_label)

        text_label = QLabel(
            "<h2>Sysext Creator Pro</h2>"
            "<p><b>Version:</b> 3.1.1</p>"
            "<p>The ultimate GUI for Fedora Atomic layers.</p>"
            "<p>Built to survive system updates and save you from writing bash scripts.</p>"
        )
        # TAHLE RÁDKA TI TAM CHYBĚLA!
        text_label.setWordWrap(True) # Force automatic line breaking
        text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(text_label)

# ==========================================
# BACKGROUND WORKER: TOOLBOX UPDATE
# ==========================================
class ToolboxUpdateWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        # We run sudo dnf update -y inside the container
        # Since the user is in the wheel group inside toolbox, sudo works without password
        cmd = ["toolbox", "run", "-c", "sysext-builder", "sudo", "dnf", "update", "-y"]
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                self.log_output.emit(line.strip())

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, "✅ Toolbox container updated successfully.")
            else:
                self.finished.emit(False, f"❌ Update failed (Exit code: {process.returncode})")
        except Exception as e:
            self.finished.emit(False, str(e))

# ==========================================
# BACKGROUND WORKER: DNF OPERATIONS
# ==========================================
class DnfAsyncWorker(QThread):
    packages_loaded = pyqtSignal(list)
    groups_loaded = pyqtSignal(list)
    group_details_loaded = pyqtSignal(list)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task="available", group_name=None):
        super().__init__()
        self.task = task
        self.group_name = group_name

    def load_installed_sysexts(self):
        """Load system extensions by checking .raw files and optional manifests."""
        try:
            batch = []
            found_extensions = {} # Dictionary to map: name -> status

            # 1. Check EXTENSIONS_DIR (These are effectively active/loaded by systemd)
            if os.path.exists(EXTENSIONS_DIR):
                for f in os.listdir(EXTENSIONS_DIR):
                    if f.endswith(".raw"):
                        found_extensions[f[:-4]] = "Active"

            # 2. Check CACHE_DIR (These are inactive, not deployed to the system yet)
            if os.path.exists(CACHE_DIR):
                for f in os.listdir(CACHE_DIR):
                    if f.endswith(".raw") and f[:-4] not in found_extensions:
                        found_extensions[f[:-4]] = "Inactive (Cache)"

            # 3. Build the data for the table and attach manifest data IF it exists
            for name, status in found_extensions.items():
                count = "Unknown"
                manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")

                # If our custom Builder created a manifest, we can count the packages
                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r') as f:
                        count = str(sum(1 for line in f if line.strip()))

                batch.append([name, "Sysext", count, status])

            if not batch:
                logging.info("[WORKER] No sysexts found in system directories.")

            self.packages_loaded.emit(batch)
        except Exception as e:
            self.error.emit(f"Failed to load extensions: {e}")

    def run(self):
        if self.task == "available": self.load_available_packages()
        elif self.task == "groups": self.load_groups()
        elif self.task == "group_details": self.load_group_details()
        elif self.task == "installed": self.load_installed_sysexts() # ADDED THIS LINE
        self.finished.emit()

    def get_all_installed_packages(self) -> set:
        """Combine host RPM database and custom sysext manifest files."""
        installed_set = set()

        # 1. Native host packages (RPM)
        try:
            cmd = ["rpm", "-qa", "--queryformat", "%{NAME}\n"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            installed_set.update(res.stdout.splitlines())
        except Exception as e:
            logging.warning(f"Failed to fetch host RPMs: {e}")

        # 2. Sysext manifest files (usually in /usr/share/sysext/manifests/)
        manifest_dir = "/usr/share/sysext/manifests"
        try:
            if os.path.exists(manifest_dir):
                for manifest in os.listdir(manifest_dir):
                    if manifest.endswith(".txt"):
                        with open(os.path.join(manifest_dir, manifest), 'r') as f:
                            pkgs = [line.strip() for line in f if line.strip()]
                            installed_set.update(pkgs)
        except Exception as e:
            logging.warning(f"Failed to read sysext manifests: {e}")

        return installed_set

    def load_available_packages(self):
        installed = self.get_all_installed_packages()
        cmd = [
            "toolbox", "run", "-c", "sysext-builder",
            "dnf", "repoquery", "--quiet", "--queryformat", "%{name}|%{version}-%{release}|%{repoid}\n"
        ]

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            batch = []
            for line in process.stdout:
                clean_line = line.strip()
                if not clean_line: continue
                parts = clean_line.split("|")
                if len(parts) == 3:
                    name, version, repo = parts
                    if name not in installed:
                        batch.append([name, version, repo, "Available"])

                if len(batch) >= 500:
                    self.packages_loaded.emit(batch)
                    batch = []

            if batch: self.packages_loaded.emit(batch)
            process.wait()
        except Exception as e:
            self.error.emit(f"DNF Data Error: {e}")

    def load_groups(self):
        cmd = ["toolbox", "run", "-c", "sysext-builder", "dnf", "group", "list", "--hidden"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            groups = []
            for line in res.stdout.splitlines():
                clean_line = line.strip()
                if not clean_line or clean_line.startswith(("ID", "Available", "Installed", "Hidden", "Environment", "Last", "Aktualizace", "Repozitáře")):
                    continue

                parts = re.split(r'\s{2,}', clean_line)
                if len(parts) >= 3:
                    groups.append([parts[0], "Group", parts[1], parts[2]])
            self.groups_loaded.emit(groups)
        except Exception as e:
            self.error.emit(f"DNF Group List Error: {e}")

    def load_group_details(self):
        installed = self.get_all_installed_packages()
        cmd = ["toolbox", "run", "-c", "sysext-builder", "env", "LANG=C", "dnf", "group", "info", "--quiet", self.group_name]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            packages = []
            parsing = False
            for line in res.stdout.splitlines():
                if ":" in line:
                    left, right = line.split(":", 1)
                    l_clean, r_clean = left.strip(), right.strip()
                    if l_clean in ["Mandatory packages", "Default packages"]:
                        parsing = True
                        if r_clean and r_clean not in installed: packages.append(r_clean)
                    elif l_clean == "" and parsing:
                        if r_clean and r_clean not in installed: packages.append(r_clean)
                    else:
                        parsing = False
            self.group_details_loaded.emit(packages)
        except Exception as e:
            self.error.emit(f"DNF Group Info Error: {e}")

    def run(self):
        if self.task == "available": self.load_available_packages()
        elif self.task == "groups": self.load_groups()
        elif self.task == "group_details": self.load_group_details()
        elif self.task == "installed": self.load_installed_sysexts() # ADDED THIS LINE
        self.finished.emit()

# ==========================================
# BACKGROUND WORKER: BUILD PROCESS (POLKIT VERSION)
# ==========================================
class BuildWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, extension_name, packages):
        super().__init__()
        self.extension_name = extension_name
        self.packages = packages

    def run(self):
        builder_script = os.path.expanduser("~/.local/bin/sysext-creator-builder.py")

        # Step 1: Run the heavy build process in Toolbox as standard user.
        # Toolbox handles internal sudo seamlessly.
        build_cmd = [
            "toolbox", "run", "-c", "sysext-builder",
            "python3", builder_script,
            "--name", self.extension_name,
            "--packages"
        ] + self.packages

        self.log_output.emit("--- PHASE 1: BUILDING IMAGE ---")
        try:
            process = subprocess.Popen(build_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                self.log_output.emit(line.strip())

            process.wait()
            if process.returncode != 0:
                self.finished.emit(False, f"Build phase failed (Exit code: {process.returncode})")
                return

        except Exception as e:
            self.finished.emit(False, f"Build process error: {e}")
            return

        # Step 2: Deploy and Activate using Polkit (pkexec)
        self.log_output.emit("\n--- PHASE 2: SYSTEM DEPLOYMENT ---")
        self.log_output.emit("Waiting for authentication... (Please check your KDE password prompt)")

        # Use global configuration constants
        source_raw = os.path.join(CACHE_DIR, f"{self.extension_name}.raw")
        dest_raw = os.path.join(EXTENSIONS_DIR, f"{self.extension_name}.raw")

        # We chain the deployment commands inside a single pkexec shell call
        # Added 'sleep 2' to ensure mount propagation, followed by tmpfiles generation
        deploy_cmd = [
            "pkexec", "sh", "-c",
            f"mkdir -p {EXTENSIONS_DIR} && mv -f {source_raw} {dest_raw} && systemd-sysext refresh && sleep 3 && systemd-tmpfiles --create"
        ]

        try:
            deploy_process = subprocess.Popen(deploy_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in deploy_process.stdout:
                self.log_output.emit(line.strip())

            deploy_process.wait()

            # Polkit exit code 126 or 127 usually means user dismissed the password dialog
            if deploy_process.returncode == 126 or deploy_process.returncode == 127:
                self.finished.emit(False, "Deployment cancelled: Authentication was rejected.")
            elif deploy_process.returncode == 0:
                self.finished.emit(True, f"Successfully built and deployed: {self.extension_name}")
            else:
                self.finished.emit(False, f"Deployment failed (Exit code: {deploy_process.returncode})")

        except Exception as e:
            self.finished.emit(False, f"Deployment error: {e}")

# ==========================================
# BACKGROUND WORKER: REMOVE EXTENSION
# ==========================================
class RemoveWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, extension_name):
        super().__init__()
        self.extension_name = extension_name

    def run(self):
        raw_path = os.path.join(EXTENSIONS_DIR, f"{self.extension_name}.raw")
        cache_path = os.path.join(CACHE_DIR, f"{self.extension_name}.raw")

        # Changed '&&' to ';' for tmpfiles, so minor warnings don't trigger a failure
        cmd = [
            "pkexec", "sh", "-c",
            f"rm -f {raw_path} {cache_path} && systemd-sysext refresh ; sleep 3 ; systemd-tmpfiles --create"
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode in (126, 127):
                self.finished.emit(False, "Removal aborted: Authentication rejected.")
            elif "rm: cannot remove" in res.stderr:
                self.finished.emit(False, f"Failed to remove files: {res.stderr}")
            else:
                self.finished.emit(True, f"Extension '{self.extension_name}' was successfully removed.")
        except Exception as e:
            self.finished.emit(False, str(e))

# ==========================================
# UI: PROGRESS DIALOG
# ==========================================
class BuildProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sysext Build Progress")
        self.resize(800, 500)
        layout = QVBoxLayout(self)

        self.status_label = QLabel("Initializing Build Engine...")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: 'Monospace';")
        layout.addWidget(self.log_view)

        self.close_btn = QPushButton("Done")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)

    def append_log(self, text):
        self.log_view.append(text)
        # Auto-scroll to bottom
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

# ==========================================
# BACKGROUND WORKER: DOCTOR DIAGNOSTICS
# ==========================================
class DoctorWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        doctor_script = os.path.expanduser("~/.local/bin/sysext-doctor.py")
        cmd = ["pkexec", "python3", doctor_script]

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                self.log_output.emit(line.strip())

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, "Diagnostics complete.")
            else:
                self.finished.emit(False, f"Diagnostics failed (Exit code: {process.returncode})")
        except Exception as e:
            self.finished.emit(False, str(e))

# ==========================================
# UI: MAIN APPLICATION WINDOW
# ==========================================
class SysextAdvancedGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sysext Creator Pro")
        self.resize(1200, 850)
        self.transaction_queue = []
        self.worker = None
        self.build_worker = None
        self.setup_ui()
        QTimer.singleShot(500, self.perform_startup_checks)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # ==========================================
        # TOP MENU BAR (File, Tools, Help)
        # ==========================================
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("File")
        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # Tools Menu
        tools_menu = menubar.addMenu("Tools")
        upd_act = QAction("🔄 Update Toolbox Container", self)
        upd_act.triggered.connect(self.update_toolbox_container)
        tools_menu.addAction(upd_act)

        clear_act = QAction("🧹 Clear Unused Image Cache", self)
        clear_act.triggered.connect(self.clear_image_cache)
        tools_menu.addAction(clear_act)

        # Help Menu
        help_menu = menubar.addMenu("Help")
        howto_act = QAction("📖 How to Use", self)
        howto_act.triggered.connect(self.show_help)
        help_menu.addAction(howto_act)

        about_act = QAction("ℹ️ About", self)
        about_act.triggered.connect(self.show_about)
        help_menu.addAction(about_act)

        # ==========================================
        # SET APPLICATION ICON (In-Window Decoration)
        # ==========================================
        # This makes the icon appear in the window title, Alt-Tab switcher, and docks
        # Use the name installed to hicolor theme (gtk-update-icon-cache handles this)
        installed_icon_theme = QIcon.fromTheme("sysext-creator")
        if not installed_icon_theme.isNull():
            self.setWindowIcon(installed_icon_theme)
        else:
            installed_icon_path = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/sysext-creator.png")
            if os.path.exists(installed_icon_path):
                self.setWindowIcon(QIcon(installed_icon_path))

        main_layout = QHBoxLayout(central_widget)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(main_splitter)

        # Left Panel (Navigation and Queue Management)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self.category_list = QListWidget()
        self.category_list.addItems([
            "📦 Available (DNF)",
            "✅ Installed (Sysext)",
            "🔄 Updates",
            "📁 Package Groups",
            "🛒 Transaction Queue (0)",
            "🩺 System Doctor"
        ])
        self.category_list.currentRowChanged.connect(self.on_category_changed)

        left_layout.addWidget(QLabel("<b>Navigation</b>"))
        left_layout.addWidget(self.category_list)

        self.btn_clear = QPushButton("Clear Transaction Queue")
        self.btn_clear.clicked.connect(self.clear_queue)
        left_layout.addWidget(self.btn_clear)

        self.btn_apply = QPushButton("Apply Transaction")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet("background-color: #2e8b57; color: white; font-weight: bold; padding: 12px;")
        self.btn_apply.clicked.connect(self.apply_transaction)
        left_layout.addWidget(self.btn_apply)

        # Right Panel (Main Content and Details)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        top_right_panel = QWidget()
        top_right_layout = QVBoxLayout(top_right_panel)

        self.status_label = QLabel("Select a category to start browsing.")
        top_right_layout.addWidget(self.status_label)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Live Filter...")
        top_right_layout.addWidget(self.search_bar)

        self.package_table = QTableView()
        self.package_model = QStandardItemModel(0, 4)
        self.package_model.setHorizontalHeaderLabels(["Name", "Version", "Repository", "State"])

        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.package_model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy_model.setFilterKeyColumn(0)
        self.search_bar.textChanged.connect(self.proxy_model.setFilterFixedString)

        self.package_table.setModel(self.proxy_model)
        self.package_table.setSortingEnabled(True)
        self.package_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.package_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.package_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.package_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.package_table.customContextMenuRequested.connect(self.show_context_menu)
        self.package_table.selectionModel().selectionChanged.connect(self.on_table_selection)

        top_right_layout.addWidget(self.package_table)

        self.details_tabs = QTabWidget()
        self.tab_info = QTextEdit()
        self.tab_info.setReadOnly(True)
        self.details_tabs.addTab(self.tab_info, "Information / Metadata")

        right_splitter.addWidget(top_right_panel)
        right_splitter.addWidget(self.details_tabs)
        right_splitter.setSizes([600, 250])
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([280, 920])

    def on_category_changed(self, index):
        self.package_model.removeRows(0, self.package_model.rowCount())
        category = self.category_list.item(index).text()

        if "Groups" in category:
            self.package_model.setHorizontalHeaderLabels(["ID", "Type", "Name", "Installed"])
        elif "Installed" in category or "Updates" in category:
            self.package_model.setHorizontalHeaderLabels(["Extension Name", "Type", "Packages", "State"])
        elif "Doctor" in category:
            self.package_model.setHorizontalHeaderLabels(["Diagnostic Output"])
            self.tab_info.setHtml("<h3>🩺 System Doctor</h3><p>Tato sekce provede hloubkovou analýzu extenzí pomocí <b>systemd-dissect</b>. Odhalí případné přesahy do hostitelského OS a vzájemné konflikty balíčků.</p><p>Pro spuštění testu klikni na tlačítko <b>Run Diagnostics</b> vlevo dole.</p>")
        else:
            self.package_model.setHorizontalHeaderLabels(["Name", "Version", "Repository", "State"])

        if "Available" in category: self.start_worker("available")
        elif "Groups" in category: self.start_worker("groups")
        elif "Installed" in category or "Updates" in category: self.start_worker("installed")
        elif "Queue" in category: self.show_queue()

        self.update_ui_state() # Ensure button changes immediately on tab switch

    def start_worker(self, task):
        if getattr(self, 'worker', None) and self.worker.isRunning(): return
        self.status_label.setText(f"⏳ Synchronizing with DNF ({task})...")
        self.worker = DnfAsyncWorker(task=task)
        if task == "groups": self.worker.groups_loaded.connect(self.on_batch_loaded)
        else: self.worker.packages_loaded.connect(self.on_batch_loaded)
        self.worker.finished.connect(lambda: self.status_label.setText("✅ Data synchronization complete."))
        self.worker.start()

    def on_batch_loaded(self, batch):
        for item in batch:
            row = [QStandardItem(str(i)) for i in item]
            self.package_model.appendRow(row)

    def on_table_selection(self):
        indexes = self.package_table.selectionModel().selectedRows()
        if not indexes: return
        real_idx = self.proxy_model.mapToSource(indexes[0])
        name = self.package_model.item(real_idx.row(), 0).text()
        v_type = self.package_model.item(real_idx.row(), 1).text()

        if v_type == "Group":
            self.tab_info.setHtml(f"<h3>Parsing DNF Group: {name}</h3><p>Retrieving package lists...</p>")
            self.worker_det = DnfAsyncWorker(task="group_details", group_name=name)
            self.worker_det.group_details_loaded.connect(self.on_group_details_ready)
            self.worker_det.start()

        elif v_type == "Sysext":
            manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")
            deps_path = os.path.join(MANIFEST_DIR, f"{name}-deps.txt")

            html = f"<h3>Extension: {name}</h3>"
            status_text = self.package_model.item(real_idx.row(), 3).text()
            html += f"<p><b>System Status:</b> {status_text}</p>"

            if os.path.exists(manifest_path):
                # Load explicitly requested packages
                with open(manifest_path, 'r') as f:
                    pkgs = sorted([line.strip() for line in f if line.strip()])
                html += "<p><b>Requested Packages:</b></p><ul>"
                html += "".join([f"<li>{p}</li>" for p in pkgs]) + "</ul>"

                # Load full dependency tree if the builder generated it
                if os.path.exists(deps_path):
                    with open(deps_path, 'r') as f:
                        deps = sorted([line.strip() for line in f if line.strip()])
                    html += f"<p><b>Full Dependency Tree ({len(deps)} items):</b></p><ul>"
                    html += "".join([f"<li><small>{d}</small></li>" for d in deps]) + "</ul>"
            else:
                # Handle external or manually created .raw images gracefully
                html += "<p><i>No manifest found. (This .raw image was likely created externally)</i></p>"

            self.tab_info.setHtml(html)

        else:
            self.tab_info.setHtml(f"<h3>{name}</h3><p>Package version: {self.package_model.item(real_idx.row(), 1).text()}</p>")

    def on_group_details_ready(self, packages):
        self.current_group_pkgs = packages
        html = f"<h3>Group Manifest ({len(packages)} unique items)</h3><ul>"
        html += "".join([f"<li>{p}</li>" for p in packages]) + "</ul>"
        self.tab_info.setHtml(html)

    def show_context_menu(self, pos):
        idx = self.package_table.selectionModel().selectedRows()
        if not idx: return

        menu = QMenu()
        curr_cat = self.category_list.currentRow()

        if curr_cat == 1: # Installed
            act = QAction("🗑️ Remove Extension", self)
            act.triggered.connect(lambda: self.remove_extension(idx))
            menu.addAction(act)
        elif curr_cat == 2: # Updates
            act = QAction("🔄 Rebuild with Latest Packages", self)
            act.triggered.connect(lambda: self.rebuild_extension(idx))
            menu.addAction(act)
        elif curr_cat == 4: # Queue
            act = QAction("❌ Remove Selection from Queue", self)
            act.triggered.connect(lambda: self.remove_from_queue(idx))
            menu.addAction(act)
        else: # Available / Groups
            act = QAction("🛒 Add Selection to Transaction Queue", self)
            act.triggered.connect(lambda: self.add_to_queue(idx))
            menu.addAction(act)

        menu.exec(self.package_table.viewport().mapToGlobal(pos))

    def add_to_queue(self, indexes):
        for idx in indexes:
            real_idx = self.proxy_model.mapToSource(idx)
            name = self.package_model.item(real_idx.row(), 0).text()
            v_type = self.package_model.item(real_idx.row(), 1).text()

            if v_type == "Group":
                if hasattr(self, 'current_group_pkgs'):
                    for p in self.current_group_pkgs:
                        if p not in self.transaction_queue: self.transaction_queue.append(p)
                    self.package_model.setItem(real_idx.row(), 3, QStandardItem("Queued 🛒"))
            else:
                if name not in self.transaction_queue:
                    self.transaction_queue.append(name)
                    self.package_model.setItem(real_idx.row(), 3, QStandardItem("Queued 🛒"))
        self.update_ui_state()

    def remove_from_queue(self, indexes):
        for idx in reversed(indexes):
            real_idx = self.proxy_model.mapToSource(idx)
            name = self.package_model.item(real_idx.row(), 0).text()
            if name in self.transaction_queue: self.transaction_queue.remove(name)
            self.package_model.removeRow(real_idx.row())
        self.update_ui_state()

    def clear_queue(self):
        self.transaction_queue.clear()
        if self.category_list.currentRow() == 4:
            self.package_model.removeRows(0, self.package_model.rowCount())
        self.update_ui_state()

    def update_ui_state(self):
        count = len(self.transaction_queue)
        self.category_list.item(4).setText(f"🛒 Transaction Queue ({count})")

        if self.category_list.currentRow() == 5: # Doctor Tab
            self.btn_apply.setEnabled(True)
            self.btn_apply.setText("🩺 Run Diagnostics")
        else:
            self.btn_apply.setEnabled(count > 0)
            self.btn_apply.setText(f"Process Transaction ({count})" if count > 0 else "Apply Transaction")

    def show_queue(self):
        self.package_model.removeRows(0, self.package_model.rowCount())
        for name in self.transaction_queue:
            row = [QStandardItem(name), QStandardItem("pending"), QStandardItem("transaction"), QStandardItem("Scheduled")]
            self.package_model.appendRow(row)

    def apply_transaction(self):
        if self.category_list.currentRow() == 5:
            self.run_doctor()
            return

        if not self.transaction_queue: return

        name, ok = QInputDialog.getText(self, "System Extension Identity",
                                        "Set a filename for the resulting .raw image:",
                                        text="custom-layer")

        if ok and name:
            self.build_dialog = BuildProgressDialog(self)
            self.build_dialog.show()

            self.build_worker = BuildWorker(name, self.transaction_queue)
            self.build_worker.log_output.connect(self.build_dialog.append_log)
            self.build_worker.finished.connect(self.on_build_finished)
            self.build_worker.start()

    def run_doctor(self):
        self.build_dialog = BuildProgressDialog(self)
        self.build_dialog.setWindowTitle("System Doctor Diagnostics")
        self.build_dialog.status_label.setText("Analyzing system extensions and configurations...")
        self.build_dialog.show()

        self.doctor_worker = DoctorWorker()
        self.doctor_worker.log_output.connect(self.build_dialog.append_log)
        self.doctor_worker.finished.connect(lambda s, m: self.build_dialog.close_btn.setEnabled(True))
        self.doctor_worker.finished.connect(lambda s, m: self.build_dialog.status_label.setText(m))
        self.doctor_worker.start()

    def remove_extension(self, indexes):
        real_idx = self.proxy_model.mapToSource(indexes[0])
        name = self.package_model.item(real_idx.row(), 0).text()

        # Don't let users delete things accidentally
        msg = f"Are you absolutely sure you want to PERMANENTLY delete the extension '{name}'?\n\nIt will be unloaded from your system immediately."
        reply = QMessageBox.question(self, 'Confirm Annihilation', msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.status_label.setText(f"🗑️ Purging {name} and reloading systemd-sysext...")
            self.remove_worker = RemoveWorker(name)
            self.remove_worker.finished.connect(self.on_remove_finished)
            self.remove_worker.start()

    def rebuild_extension(self, indexes):
        real_idx = self.proxy_model.mapToSource(indexes[0])
        name = self.package_model.item(real_idx.row(), 0).text()

        manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")
        if not os.path.exists(manifest_path):
            QMessageBox.warning(self, "Error", f"Cannot rebuild: Manifest {manifest_path} not found.")
            return

        with open(manifest_path, 'r') as f:
            packages = [line.strip() for line in f if line.strip()]

        msg = f"Rebuild '{name}' with the latest packages from Fedora repositories?\n\nThis will re-download and update: {', '.join(packages)}"

        if QMessageBox.question(self, 'Confirm Rebuild', msg) == QMessageBox.StandardButton.Yes:
            self.build_dialog = BuildProgressDialog(self)
            self.build_dialog.show()

            # Reuse the existing BuildWorker! It will overwrite the old .raw file perfectly
            self.build_worker = BuildWorker(name, packages)
            self.build_worker.log_output.connect(self.build_dialog.append_log)
            self.build_worker.finished.connect(self.on_build_finished)
            self.build_worker.start()

    def on_remove_finished(self, success, message):
        if success:
            # Clear the bottom detail panel so it doesn't show the ghost of the deleted extension
            self.tab_info.clear()
            QMessageBox.information(self, "Success", message)

            # Re-trigger the category load
            curr = self.category_list.currentRow()
            self.on_category_changed(curr)
        else:
            self.status_label.setText("❌ Removal failed.")
            QMessageBox.warning(self, "Error", message)

        self.status_label.setText("✅ Ready." if success else "❌ Removal failed.")

    def on_build_finished(self, success, message):
        self.build_dialog.progress.setRange(0, 100)
        self.build_dialog.progress.setValue(100)
        self.build_dialog.status_label.setText(message)
        self.build_dialog.close_btn.setEnabled(True)

        if success:
            self.clear_queue()
            QMessageBox.information(self, "Build Complete", "The new system extension has been created.")
            self.on_category_changed(self.category_list.currentRow())

    def closeEvent(self, event):
        try:
            for w in [getattr(self, 'worker', None), getattr(self, 'build_worker', None)]:
                if w and w.isRunning():
                    w.terminate()
                    w.wait(1000)
        except: pass
        event.accept()

    # ==========================================
    # MENU ACTIONS
    # ==========================================
    def show_help(self):
        dlg = HelpDialog(self)
        dlg.exec()

    def show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def clear_image_cache(self):
        msg = "Are you sure you want to clear the local image cache?\n\nThis will delete all unapplied .raw extensions waiting in ~/.cache/sysext-creator/."
        reply = QMessageBox.question(self, 'Clear Cache', msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if os.path.exists(CACHE_DIR):
                try:
                    shutil.rmtree(CACHE_DIR)
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    QMessageBox.information(self, "Success", "Cache has been completely cleared.")
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to clear cache: {e}")

    def update_toolbox_container(self):
        msg = "Do you want to run 'dnf update' inside the sysext-builder Toolbox container?\n\nThis will ensure your container uses the latest libraries and avoids dependency mismatches. It may take a few minutes."
        reply = QMessageBox.question(self, 'Update Container', msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.build_dialog = BuildProgressDialog(self)
            self.build_dialog.setWindowTitle("Updating Container Environment")
            self.build_dialog.status_label.setText("Starting DNF update inside sysext-builder...")
            self.build_dialog.show()

            self.upd_worker = ToolboxUpdateWorker()
            self.upd_worker.log_output.connect(self.build_dialog.append_log)
            self.upd_worker.finished.connect(lambda s, m: self.build_dialog.close_btn.setEnabled(True))
            self.upd_worker.finished.connect(lambda s, m: self.build_dialog.status_label.setText(m))
            self.upd_worker.start()

    def perform_startup_checks(self):
        try:
            # 1. Zjistíme verzi hostitele (Fedory)
            host_ver = None
            with open("/etc/os-release", "r") as f:
                for line in f:
                    if line.startswith("VERSION_ID="):
                        host_ver = line.strip().split("=")[1].strip('"')

            # 2. Zkontrolujeme, jestli kontejner vůbec existuje (rychlý podman check)
            check_cmd = subprocess.run(["podman", "container", "exists", "sysext-builder"])
            if check_cmd.returncode != 0:
                self.prompt_container_rebuild(
                    "Missing Build Environment",
                    "The 'sysext-builder' container does not exist. It is required to safely build extensions.\n\nWould you like to create it now?"
                )
                return

            # 3. Zkontrolujeme verzi OS uvnitř kontejneru
            # Spustíme toolbox run, který ho i probudí, pokud spí
            res = subprocess.run(["toolbox", "run", "-c", "sysext-builder", "cat", "/etc/os-release"], capture_output=True, text=True)
            if res.returncode == 0:
                cont_ver = None
                for line in res.stdout.splitlines():
                    if line.startswith("VERSION_ID="):
                        cont_ver = line.strip().split("=")[1].strip('"')

                # Porovnání
                if host_ver and cont_ver and host_ver != cont_ver:
                    self.prompt_container_rebuild(
                        "OS Upgrade Detected",
                        f"Your Host OS is Fedora {host_ver}, but the builder container is stuck on Fedora {cont_ver}.\n\nWould you like to rebuild the container now to prevent library conflicts?"
                    )

        except Exception as e:
            logging.warning(f"Startup check failed: {e}")

    def prompt_container_rebuild(self, title, msg):
        """A helper function that recycles our Rebuild Worker menu from Tools"""
        reply = QMessageBox.question(self, title, msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.build_dialog = BuildProgressDialog(self)
            self.build_dialog.setWindowTitle(title)
            self.build_dialog.status_label.setText("Working with podman/toolbox... This may take a few minutes to download the base image.")
            self.build_dialog.show()

            # Znovu použijeme Workera, kterého jsi předtím vyrobil!
            self.rebuild_worker = ToolboxRebuildWorker()
            self.rebuild_worker.log_output.connect(self.build_dialog.append_log)
            self.rebuild_worker.finished.connect(lambda s, m: self.build_dialog.close_btn.setEnabled(True))
            self.rebuild_worker.finished.connect(lambda s, m: self.build_dialog.status_label.setText(m))
            self.rebuild_worker.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SysextAdvancedGUI()
    window.show()
    sys.exit(app.exec())
