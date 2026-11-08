#!/usr/bin/python3
# Sysext Creator GUI Pro v3.2.4
# Unified architecture delegating all backend operations to sysext-cli.py

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
                             QDialog, QProgressBar, QInputDialog, QTextBrowser)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QTimer
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction, QIcon, QPixmap

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ==========================================
# GLOBAL CONFIGURATION
# ==========================================
CACHE_DIR = os.path.expanduser("~/.cache/sysext-creator")
EXTENSIONS_DIR = "/var/lib/extensions"
MANIFEST_DIR = "/usr/share/sysext/manifests"
BIN_DIR = os.path.expanduser("~/.local/bin")
CLI_SCRIPT = os.path.join(BIN_DIR, "sysext-cli.py")


def get_cli_path():
    """Locate sysext-cli script."""
    if os.path.exists(CLI_SCRIPT):
        return CLI_SCRIPT
    which_cli = shutil.which("sysext-cli")
    if which_cli:
        return which_cli
    return CLI_SCRIPT


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
        <h2>Welcome to Sysext Creator Pro v3.2</h2>
        <p>This tool securely builds and manages systemd-sysext layered images for Fedora Atomic / Kinoite.</p>

        <h3>1. Searching & Queueing</h3>
        <p>Use the <b>Available (DNF)</b> tab to browse the repository catalog. Select desired packages, right-click, and add them to the <b>Transaction Queue</b>.</p>

        <h3>2. Building an Extension</h3>
        <p>Click <b>Process Transaction</b>. The build process runs isolated inside a Toolbox container via <code>sysext-cli</code> and creates an optimized EROFS image.</p>

        <h3>3. Updates & /etc Migration</h3>
        <p>Configuration files in <code>/etc</code> are automatically translated into <code>tmpfiles.d</code> symlinks. When updating or removing an extension, <code>sysext-cli</code> guarantees clean removal of dangling symlinks.</p>

        <h3>4. System Doctor</h3>
        <p>Run diagnostics to verify version compatibility, host shadowing, and repository paths (supporting Fedora 45+ layouts).</p>
        """)
        layout.addWidget(browser)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ℹ️ About Sysext Creator Pro")
        self.setFixedSize(500, 220)
        layout = QHBoxLayout(self)

        icon_label = QLabel()
        icon_path = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/sysext-creator.png")
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(110, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pix)
        else:
            icon_label.setText("📦")
        layout.addWidget(icon_label)

        text_label = QLabel(
            "<h2>Sysext Creator Pro</h2>"
            "<p><b>Version:</b> 3.2 (Unified CLI Backend)</p>"
            "<p>Robust, atomic userspace extensions on Fedora Kinoite / Silverblue.</p>"
            "<p>Features DNF5 compatibility, host OS smart pruning, /etc tmpfiles migration, and automated cleanup.</p>"
        )
        text_label.setWordWrap(True)
        text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(text_label)


# ==========================================
# UI: PROGRESS DIALOG
# ==========================================
class BuildProgressDialog(QDialog):
    def __init__(self, title="Operation Progress", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 520)
        layout = QVBoxLayout(self)

        self.status_label = QLabel("Initializing operation...")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #1a1b26; color: #7aa2f7; font-family: 'Monospace'; font-size: 12px;")
        layout.addWidget(self.log_view)

        self.close_btn = QPushButton("Done")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn)

    def append_log(self, text):
        self.log_view.append(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())


# ==========================================
# WORKERS DELEGATING TO SYSEXT-CLI
# ==========================================
class BuildWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, extension_name, packages):
        super().__init__()
        self.extension_name = extension_name
        self.packages = packages

    def run(self):
        cli = get_cli_path()
        if not os.path.exists(cli):
            self.finished.emit(False, f"CLI backend not found at {cli}")
            return

        cmd = [sys.executable, cli, "install", self.extension_name] + self.packages
        self.log_output.emit(f"🚀 Running: {' '.join(cmd)}\n")

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            for line in process.stdout:
                self.log_output.emit(line.rstrip())

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, f"✅ Extension '{self.extension_name}' built and deployed successfully.")
            else:
                self.finished.emit(False, f"❌ Build failed with exit code: {process.returncode}")
        except Exception as e:
            self.finished.emit(False, f"Process execution error: {e}")


class UpdateWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, extension_name=None, update_all=False):
        super().__init__()
        self.extension_name = extension_name
        self.update_all = update_all

    def run(self):
        cli = get_cli_path()
        if not os.path.exists(cli):
            self.finished.emit(False, f"CLI backend not found at {cli}")
            return

        cmd = [sys.executable, cli, "update"]
        if self.update_all:
            cmd.append("--all")
        else:
            cmd.append(self.extension_name)

        self.log_output.emit(f"🔄 Running update: {' '.join(cmd)}\n")

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            for line in process.stdout:
                self.log_output.emit(line.rstrip())

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, "✅ Update completed successfully.")
            else:
                self.finished.emit(False, f"❌ Update finished with exit code {process.returncode}")
        except Exception as e:
            self.finished.emit(False, f"Execution error: {e}")


class RemoveWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, extension_name):
        super().__init__()
        self.extension_name = extension_name

    def run(self):
        cli = get_cli_path()
        if not os.path.exists(cli):
            self.finished.emit(False, f"CLI backend not found at {cli}")
            return

        cmd = [sys.executable, cli, "remove", self.extension_name]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            if res.returncode == 0:
                self.finished.emit(True, f"Extension '{self.extension_name}' and its /etc symlinks were removed.")
            elif res.returncode in (126, 127):
                self.finished.emit(False, "Removal cancelled: Authentication rejected.")
            else:
                err = res.stderr.strip() or res.stdout.strip()
                self.finished.emit(False, f"Removal failed (exit {res.returncode}): {err}")
        except Exception as e:
            self.finished.emit(False, str(e))


class DoctorWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        cli = get_cli_path()
        if not os.path.exists(cli):
            self.finished.emit(False, f"CLI backend not found at {cli}")
            return

        cmd = [sys.executable, cli, "doctor"]
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            for line in process.stdout:
                self.log_output.emit(line.rstrip())

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, "Diagnostics complete.")
            else:
                self.finished.emit(False, f"Diagnostics exited with code {process.returncode}")
        except Exception as e:
            self.finished.emit(False, str(e))


class ToolboxUpdateWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        cmd = ["toolbox", "run", "-c", "sysext-builder", "sudo", "dnf", "update", "-y"]
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            for line in process.stdout:
                self.log_output.emit(line.rstrip())

            process.wait()
            if process.returncode == 0:
                self.finished.emit(True, "✅ Toolbox container updated successfully.")
            else:
                self.finished.emit(False, f"❌ Update failed (Exit code: {process.returncode})")
        except Exception as e:
            self.finished.emit(False, str(e))


class ToolboxRebuildWorker(QThread):
    log_output = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            self.log_output.emit("Removing previous 'sysext-builder' container...")
            subprocess.run(["toolbox", "rm", "-f", "sysext-builder"], capture_output=True)

            self.log_output.emit("Creating clean 'sysext-builder' container matching host OS...")
            res = subprocess.run(["toolbox", "create", "-c", "sysext-builder"], capture_output=True, text=True)

            if res.returncode == 0:
                self.finished.emit(True, "✅ Container successfully rebuilt.")
            else:
                self.finished.emit(False, f"❌ Failed to create container: {res.stderr}")
        except Exception as e:
            self.finished.emit(False, str(e))


# ==========================================
# BACKGROUND WORKER: DNF DISCOVERY
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

    def run(self):
        if self.task == "available":
            self.load_available_packages()
        elif self.task == "groups":
            self.load_groups()
        elif self.task == "group_details":
            self.load_group_details()
        elif self.task == "installed":
            self.load_installed_sysexts()
        self.finished.emit()

    def get_all_installed_packages(self) -> set:
        installed_set = set()
        try:
            cmd = ["rpm", "--root", "/run/host", "-qa", "--queryformat", "%{NAME}\n"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            installed_set.update(res.stdout.splitlines())
        except Exception:
            try:
                cmd = ["rpm", "-qa", "--queryformat", "%{NAME}\n"]
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                installed_set.update(res.stdout.splitlines())
            except Exception as e:
                logging.warning(f"Failed to fetch host RPMs: {e}")

        if os.path.exists(MANIFEST_DIR):
            for manifest in os.listdir(MANIFEST_DIR):
                if manifest.endswith(".txt") and not manifest.endswith(("-deps.txt", "-etc.txt")):
                    try:
                        with open(os.path.join(MANIFEST_DIR, manifest), 'r') as f:
                            pkgs = [line.strip() for line in f if line.strip()]
                            installed_set.update(pkgs)
                    except Exception:
                        pass
        return installed_set

    def load_installed_sysexts(self):
        try:
            batch = []
            found_extensions = {}

            if os.path.exists(EXTENSIONS_DIR):
                for f in os.listdir(EXTENSIONS_DIR):
                    if f.endswith(".raw"):
                        found_extensions[f[:-4]] = "Active"

            if os.path.exists(CACHE_DIR):
                for f in os.listdir(CACHE_DIR):
                    if f.endswith(".raw") and f[:-4] not in found_extensions:
                        found_extensions[f[:-4]] = "Inactive (Cache)"

            for name, status in found_extensions.items():
                count = "Unknown"
                version = "unknown"

                manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")
                version_path = os.path.join(MANIFEST_DIR, f"{name}.version")

                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r') as f:
                        count = str(sum(1 for line in f if line.strip()))

                if os.path.exists(version_path):
                    with open(version_path, 'r') as f:
                        version = f.read().strip()

                batch.append([name, version, count, status])

            self.packages_loaded.emit(batch)
        except Exception as e:
            self.error.emit(f"Failed to load extensions: {e}")

    def load_available_packages(self):
        installed = self.get_all_installed_packages()
        cmd = [
            "toolbox", "run", "-c", "sysext-builder",
            "dnf", "repoquery", "--quiet", "--queryformat", "%{name}|%{version}-%{release}|%{repoid}\n"
        ]

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            batch = []
            for line in process.stdout:
                clean_line = line.strip()
                if not clean_line or "|" not in clean_line:
                    continue
                parts = clean_line.split("|")
                if len(parts) == 3:
                    name, version, repo = parts
                    if name not in installed:
                        batch.append([name, version, repo, "Available"])

                if len(batch) >= 500:
                    self.packages_loaded.emit(batch)
                    batch = []

            if batch:
                self.packages_loaded.emit(batch)
            process.wait()
        except Exception as e:
            self.error.emit(f"DNF Data Error: {e}")

    def load_groups(self):
        cmd = ["toolbox", "run", "-c", "sysext-builder", "dnf", "group", "list", "--hidden"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
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
            res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            packages = []
            parsing = False
            for line in res.stdout.splitlines():
                if ":" in line:
                    left, right = line.split(":", 1)
                    l_clean, r_clean = left.strip(), right.strip()
                    if l_clean in ["Mandatory packages", "Default packages"]:
                        parsing = True
                        if r_clean and r_clean not in installed:
                            packages.append(r_clean)
                    elif l_clean == "" and parsing:
                        if r_clean and r_clean not in installed:
                            packages.append(r_clean)
                    else:
                        parsing = False
            self.group_details_loaded.emit(packages)
        except Exception as e:
            self.error.emit(f"DNF Group Info Error: {e}")


# ==========================================
# MAIN APPLICATION WINDOW
# ==========================================
class SysextAdvancedGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sysext Creator Pro")
        self.resize(1200, 850)
        self.transaction_queue = []
        self.worker = None
        self.build_worker = None
        self.remove_worker = None
        self.doctor_worker = None
        self.update_worker = None

        self.setup_ui()
        QTimer.singleShot(400, self.perform_startup_checks)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Menu Bar
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        tools_menu = menubar.addMenu("Tools")
        upd_all_act = QAction("🔄 Update All System Extensions", self)
        upd_all_act.triggered.connect(self.update_all_extensions)
        tools_menu.addAction(upd_all_act)

        upd_toolbox_act = QAction("🛠️ Update Toolbox Container (DNF)", self)
        upd_toolbox_act.triggered.connect(self.update_toolbox_container)
        tools_menu.addAction(upd_toolbox_act)

        tools_menu.addSeparator()
        clear_act = QAction("🧹 Clear Cache (~/.cache/sysext-creator)", self)
        clear_act.triggered.connect(self.clear_image_cache)
        tools_menu.addAction(clear_act)

        help_menu = menubar.addMenu("Help")
        howto_act = QAction("📖 How to Use", self)
        howto_act.triggered.connect(self.show_help)
        help_menu.addAction(howto_act)

        about_act = QAction("ℹ️ About", self)
        about_act.triggered.connect(self.show_about)
        help_menu.addAction(about_act)

        # Application Icon
        app_icon = QIcon.fromTheme("sysext-creator")
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        else:
            p = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/sysext-creator.png")
            if os.path.exists(p):
                self.setWindowIcon(QIcon(p))

        main_layout = QHBoxLayout(central_widget)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(main_splitter)

        # Left Panel (Navigation)
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

        # Right Panel
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        top_right_panel = QWidget()
        top_right_layout = QVBoxLayout(top_right_panel)

        self.status_label = QLabel("Select a category to start browsing.")
        top_right_layout.addWidget(self.status_label)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Live filter...")
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
        self.details_tabs.addTab(self.tab_info, "Information / Manifest")

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
            self.package_model.setHorizontalHeaderLabels(["Extension Name", "Version", "Packages", "State"])
        elif "Doctor" in category:
            self.package_model.setHorizontalHeaderLabels(["System Doctor Diagnostics"])
            self.tab_info.setHtml(
                "<h3>🩺 System Doctor</h3>"
                "<p>Runs deep diagnostics via <code>sysext-cli doctor</code>.</p>"
                "<p>Checks include: Fedora 45+ repo layout, host OS version mismatches, and orphan symlinks in <code>/etc</code>.</p>"
                "<p>Click <b>Run Diagnostics</b> in the lower left to begin.</p>"
            )
        else:
            self.package_model.setHorizontalHeaderLabels(["Name", "Version", "Repository", "State"])

        if "Available" in category:
            self.start_worker("available")
        elif "Groups" in category:
            self.start_worker("groups")
        elif "Installed" in category or "Updates" in category:
            self.start_worker("installed")
        elif "Queue" in category:
            self.show_queue()

        self.update_ui_state()

    def start_worker(self, task):
        if getattr(self, 'worker', None) and self.worker.isRunning():
            return
        self.status_label.setText(f"⏳ Synchronizing data ({task})...")
        self.worker = DnfAsyncWorker(task=task)
        if task == "groups":
            self.worker.groups_loaded.connect(self.on_batch_loaded)
        else:
            self.worker.packages_loaded.connect(self.on_batch_loaded)
        self.worker.finished.connect(lambda: self.status_label.setText("✅ Synchronization complete."))
        self.worker.start()

    def on_batch_loaded(self, batch):
        for item in batch:
            row = [QStandardItem(str(i)) for i in item]
            self.package_model.appendRow(row)

    def on_table_selection(self):
        indexes = self.package_table.selectionModel().selectedRows()
        if not indexes:
            return
        real_idx = self.proxy_model.mapToSource(indexes[0])
        name = self.package_model.item(real_idx.row(), 0).text()
        col1 = self.package_model.item(real_idx.row(), 1).text()
        curr_cat = self.category_list.currentRow()

        if curr_cat == 3:  # Groups
            self.tab_info.setHtml(f"<h3>Parsing DNF Group: {name}</h3><p>Retrieving package lists...</p>")
            self.worker_det = DnfAsyncWorker(task="group_details", group_name=name)
            self.worker_det.group_details_loaded.connect(self.on_group_details_ready)
            self.worker_det.start()

        elif curr_cat in (1, 2):  # Installed / Updates
            manifest_path = os.path.join(MANIFEST_DIR, f"{name}.txt")
            deps_path = os.path.join(MANIFEST_DIR, f"{name}-deps.txt")
            etc_path = os.path.join(MANIFEST_DIR, f"{name}-etc.txt")
            version_path = os.path.join(MANIFEST_DIR, f"{name}.version")

            ver_val = "unknown"
            if os.path.exists(version_path):
                try:
                    with open(version_path, 'r') as vf:
                        ver_val = vf.read().strip()
                except Exception:
                    pass

            html = f"<h3>Extension: {name}</h3>"
            status_text = self.package_model.item(real_idx.row(), 3).text()
            html += f"<p><b>Version:</b> {ver_val} | <b>Status:</b> {status_text}</p>"

            if os.path.exists(manifest_path):
                with open(manifest_path, 'r') as f:
                    pkgs = sorted([line.strip() for line in f if line.strip()])
                html += f"<p><b>Base Packages ({len(pkgs)}):</b></p><ul>"
                html += "".join([f"<li><b>{p}</b></li>" for p in pkgs]) + "</ul>"

            if os.path.exists(deps_path):
                with open(deps_path, 'r') as f:
                    deps = sorted([line.strip() for line in f if line.strip()])
                html += f"<p><b>Full Dependency Payload ({len(deps)} total RPMs):</b></p><ul>"
                html += "".join([f"<li><small>{d}</small></li>" for d in deps]) + "</ul>"

            if os.path.exists(etc_path):
                with open(etc_path, 'r') as f:
                    etc_files = sorted([line.strip() for line in f if line.strip()])
                html += f"<p><b>Managed /etc Templates ({len(etc_files)} symlinks):</b></p><ul>"
                html += "".join([f"<li><code>/etc/{ef}</code></li>" for ef in etc_files]) + "</ul>"

            if not os.path.exists(manifest_path):
                html += "<p><i>No manifest found (extension may have been created manually).</i></p>"

            self.tab_info.setHtml(html)
        else:
            self.tab_info.setHtml(f"<h3>{name}</h3><p>Version / Details: {col1}</p>")

    def on_group_details_ready(self, packages):
        self.current_group_pkgs = packages
        html = f"<h3>Group Manifest ({len(packages)} packages)</h3><ul>"
        html += "".join([f"<li>{p}</li>" for p in packages]) + "</ul>"
        self.tab_info.setHtml(html)

    def show_context_menu(self, pos):
        idx = self.package_table.selectionModel().selectedRows()
        if not idx:
            return

        menu = QMenu()
        curr_cat = self.category_list.currentRow()

        if curr_cat == 1:  # Installed
            act_rm = QAction("🗑️ Remove Extension", self)
            act_rm.triggered.connect(lambda: self.remove_extension(idx))
            menu.addAction(act_rm)

            act_upd = QAction("🔄 Update Extension", self)
            act_upd.triggered.connect(lambda: self.rebuild_extension(idx))
            menu.addAction(act_upd)
        elif curr_cat == 2:  # Updates
            act_upd = QAction("🔄 Rebuild with Latest Packages", self)
            act_upd.triggered.connect(lambda: self.rebuild_extension(idx))
            menu.addAction(act_upd)
        elif curr_cat == 4:  # Queue
            act_rm_q = QAction("❌ Remove from Queue", self)
            act_rm_q.triggered.connect(lambda: self.remove_from_queue(idx))
            menu.addAction(act_rm_q)
        else:  # Available / Groups
            act_add = QAction("🛒 Add to Transaction Queue", self)
            act_add.triggered.connect(lambda: self.add_to_queue(idx))
            menu.addAction(act_add)

        menu.exec(self.package_table.viewport().mapToGlobal(pos))

    def add_to_queue(self, indexes):
        for idx in indexes:
            real_idx = self.proxy_model.mapToSource(idx)
            name = self.package_model.item(real_idx.row(), 0).text()
            v_type = self.package_model.item(real_idx.row(), 1).text()

            if v_type == "Group":
                if hasattr(self, 'current_group_pkgs'):
                    for p in self.current_group_pkgs:
                        if p not in self.transaction_queue:
                            self.transaction_queue.append(p)
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
            if name in self.transaction_queue:
                self.transaction_queue.remove(name)
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

        if self.category_list.currentRow() == 5:  # Doctor
            self.btn_apply.setEnabled(True)
            self.btn_apply.setText("🩺 Run Diagnostics")
        else:
            self.btn_apply.setEnabled(count > 0)
            self.btn_apply.setText(f"Process Transaction ({count})" if count > 0 else "Apply Transaction")

    def show_queue(self):
        self.package_model.removeRows(0, self.package_model.rowCount())
        for name in self.transaction_queue:
            row = [QStandardItem(name), QStandardItem("pending"), QStandardItem("queue"), QStandardItem("Scheduled")]
            self.package_model.appendRow(row)

    def apply_transaction(self):
        if self.category_list.currentRow() == 5:
            self.run_doctor()
            return

        if not self.transaction_queue:
            return

        name, ok = QInputDialog.getText(
            self,
            "System Extension Identity",
            "Set layer name (letters, numbers, '-' and '_' only):",
            text="custom-layer"
        )

        if ok and name:
            clean_name = name.strip()
            if not re.match(r'^[a-zA-Z0-9_\-\.]+$', clean_name):
                QMessageBox.warning(self, "Invalid Name", "The extension name contains invalid characters.")
                return

            self.build_dialog = BuildProgressDialog(f"Building: {clean_name}", self)
            self.build_dialog.show()

            self.build_worker = BuildWorker(clean_name, self.transaction_queue)
            self.build_worker.log_output.connect(self.build_dialog.append_log)
            self.build_worker.finished.connect(self.on_build_finished)
            self.build_worker.start()

    def run_doctor(self):
        self.build_dialog = BuildProgressDialog("System Diagnostics", self)
        self.build_dialog.status_label.setText("Running sysext-cli doctor...")
        self.build_dialog.show()

        self.doctor_worker = DoctorWorker()
        self.doctor_worker.log_output.connect(self.build_dialog.append_log)
        self.doctor_worker.finished.connect(lambda s, m: self.build_dialog.close_btn.setEnabled(True))
        self.doctor_worker.finished.connect(lambda s, m: self.build_dialog.status_label.setText(m))
        self.doctor_worker.start()

    def remove_extension(self, indexes):
        real_idx = self.proxy_model.mapToSource(indexes[0])
        name = self.package_model.item(real_idx.row(), 0).text()

        msg = (f"Are you sure you want to completely remove '{name}'?\n\n"
               f"sysext-cli will safely remove the layer and purge all associated /etc symlinks.")
        reply = QMessageBox.question(self, 'Confirm Removal', msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.status_label.setText(f"🗑️ Removing {name} via sysext-cli...")
            self.remove_worker = RemoveWorker(name)
            self.remove_worker.finished.connect(self.on_remove_finished)
            self.remove_worker.start()

    def rebuild_extension(self, indexes):
        real_idx = self.proxy_model.mapToSource(indexes[0])
        name = self.package_model.item(real_idx.row(), 0).text()

        msg = f"Update extension '{name}' to latest package versions via sysext-cli?"
        if QMessageBox.question(self, 'Confirm Update', msg) == QMessageBox.StandardButton.Yes:
            self.build_dialog = BuildProgressDialog(f"Updating: {name}", self)
            self.build_dialog.show()

            self.update_worker = UpdateWorker(extension_name=name)
            self.update_worker.log_output.connect(self.build_dialog.append_log)
            self.update_worker.finished.connect(self.on_build_finished)
            self.update_worker.start()

    def update_all_extensions(self):
        msg = "Rebuild and update all active system extensions against latest repository packages?"
        if QMessageBox.question(self, 'Update All Extensions', msg) == QMessageBox.StandardButton.Yes:
            self.build_dialog = BuildProgressDialog("Updating All Extensions", self)
            self.build_dialog.show()

            self.update_worker = UpdateWorker(update_all=True)
            self.update_worker.log_output.connect(self.build_dialog.append_log)
            self.update_worker.finished.connect(self.on_build_finished)
            self.update_worker.start()

    def on_remove_finished(self, success, message):
        if success:
            self.tab_info.clear()
            QMessageBox.information(self, "Success", message)
            self.on_category_changed(self.category_list.currentRow())
        else:
            QMessageBox.warning(self, "Error", message)
        self.status_label.setText("✅ Ready." if success else "❌ Removal failed.")

    def on_build_finished(self, success, message):
        self.build_dialog.progress.setRange(0, 100)
        self.build_dialog.progress.setValue(100)
        self.build_dialog.status_label.setText(message)
        self.build_dialog.close_btn.setEnabled(True)

        if success:
            self.clear_queue()
            QMessageBox.information(self, "Success", message)
            self.on_category_changed(self.category_list.currentRow())

    def closeEvent(self, event):
        try:
            for w in [self.worker, self.build_worker, self.remove_worker, self.doctor_worker, self.update_worker]:
                if w and w.isRunning():
                    w.terminate()
                    w.wait(1000)
        except Exception:
            pass
        event.accept()

    def show_help(self):
        HelpDialog(self).exec()

    def show_about(self):
        AboutDialog(self).exec()

    def clear_image_cache(self):
        msg = "Delete all unapplied images in ~/.cache/sysext-creator/?"
        if QMessageBox.question(self, 'Clear Cache', msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if os.path.exists(CACHE_DIR):
                try:
                    shutil.rmtree(CACHE_DIR)
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    QMessageBox.information(self, "Success", "Cache cleared.")
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to clear cache: {e}")

    def update_toolbox_container(self):
        msg = "Run 'dnf update' inside the 'sysext-builder' Toolbox container?"
        if QMessageBox.question(self, 'Update Container', msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.build_dialog = BuildProgressDialog("Updating Toolbox Container", self)
            self.build_dialog.show()

            self.upd_worker = ToolboxUpdateWorker()
            self.upd_worker.log_output.connect(self.build_dialog.append_log)
            self.upd_worker.finished.connect(lambda s, m: self.build_dialog.close_btn.setEnabled(True))
            self.upd_worker.finished.connect(lambda s, m: self.build_dialog.status_label.setText(m))
            self.upd_worker.start()

    def perform_startup_checks(self):
        try:
            host_ver = None
            for p in ["/etc/os-release", "/usr/lib/os-release"]:
                if os.path.exists(p):
                    with open(p, "r") as f:
                        for line in f:
                            if line.startswith("VERSION_ID="):
                                host_ver = line.strip().split("=")[1].strip('"\'')
                    break

            check_cmd = subprocess.run(["podman", "container", "exists", "sysext-builder"])
            if check_cmd.returncode != 0:
                self.prompt_container_rebuild(
                    "Missing Build Environment",
                    "The 'sysext-builder' container is required to build extensions.\n\nCreate it now?"
                )
                return

            res = subprocess.run(["toolbox", "run", "-c", "sysext-builder", "cat", "/etc/os-release"], capture_output=True, text=True)
            if res.returncode == 0:
                cont_ver = None
                for line in res.stdout.splitlines():
                    if line.startswith("VERSION_ID="):
                        cont_ver = line.strip().split("=")[1].strip('"\'')

                if host_ver and cont_ver and host_ver != cont_ver:
                    self.prompt_container_rebuild(
                        "OS Version Mismatch",
                        f"Host OS is Fedora {host_ver}, but the toolbox container is on Fedora {cont_ver}.\n\nRebuild container now?"
                    )
        except Exception as e:
            logging.warning(f"Startup check failed: {e}")

    def prompt_container_rebuild(self, title, msg):
        if QMessageBox.question(self, title, msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.build_dialog = BuildProgressDialog(title, self)
            self.build_dialog.status_label.setText("Pulling image and provisioning container...")
            self.build_dialog.show()

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
