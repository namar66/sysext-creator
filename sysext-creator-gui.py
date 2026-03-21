#!/usr/bin/python3

# Sysext-Creator GUI v3.0 - Thread Safe & Auto-Updater
# Tabs: Manager, Creator, Doctor, Search, Updater

import sys
import os
import varlink
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel,
                             QPushButton, QMessageBox, QHBoxLayout,
                             QLineEdit, QProgressBar, QTabWidget, QPlainTextEdit,
                             QHeaderView, QTableWidget, QTableWidgetItem)
from PyQt6.QtCore import QThread, pyqtSignal, QProcess

SOCKET_PATH = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"
CONTAINER_NAME = "sysext-builder"
BUILDER_SCRIPT = os.path.expanduser("/run/host/usr/local/bin/sysext-creator-builder.py")

class DeployWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, name, path, force=False):
        super().__init__()
        self.name, self.path, self.force = name, path, force

    def run(self):
        try:
            with varlink.Client(address=SOCKET_PATH) as client:
                with client.open(INTERFACE) as remote:
                    reply = remote.DeploySysext(self.name, self.path, self.force)
                    self.finished.emit(reply)
        except Exception as e:
            self.error.emit(str(e))

class SysextManagerGUI(QWidget):
    def __init__(self):
        super().__init__()
        # Seznam pro bezpečné uchování běžících vláken (ochrana proti Garbage Collectoru)
        self.active_workers = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Sysext Creator Pro v4.1")
        self.setMinimumSize(1000, 700)

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- TAB 1: MANAGER ---
        self.tab_manager = QWidget()
        m_layout = QVBoxLayout(self.tab_manager)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Version", "Packages"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        m_layout.addWidget(self.table)

        m_btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh List")
        self.refresh_btn.clicked.connect(self.update_list)
        self.remove_btn = QPushButton("🗑️ Remove Selected")
        self.remove_btn.clicked.connect(self.remove_selected)
        m_btn_layout.addWidget(self.refresh_btn)
        m_btn_layout.addWidget(self.remove_btn)
        m_layout.addLayout(m_btn_layout)

        # --- TAB 2: CREATOR ---
        self.tab_creator = QWidget()
        c_layout = QVBoxLayout(self.tab_creator)
        self.name_in = QLineEdit()
        self.name_in.setPlaceholderText("Extension name (e.g. tools)")
        self.pkgs_in = QLineEdit()
        self.pkgs_in.setPlaceholderText("RPM packages (e.g. htop nmap)")
        c_layout.addWidget(QLabel("Layer Name:"))
        c_layout.addWidget(self.name_in)
        c_layout.addWidget(QLabel("Packages:"))
        c_layout.addWidget(self.pkgs_in)
        self.build_btn = QPushButton("🔨 Build & Deploy")
        self.build_btn.clicked.connect(self.start_build)
        c_layout.addWidget(self.build_btn)
        self.build_log = QPlainTextEdit()
        self.build_log.setReadOnly(True)
        self.build_log.setStyleSheet("background: #1e1e1e; color: #00ff00; font-family: monospace;")
        c_layout.addWidget(self.build_log)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        c_layout.addWidget(self.progress_bar)

        # --- TAB 3: DOCTOR ---
        self.tab_doctor = QWidget()
        d_layout = QVBoxLayout(self.tab_doctor)
        self.doctor_btn = QPushButton("🩺 Run Diagnostic Scan")
        self.doctor_btn.clicked.connect(self.run_doctor)
        d_layout.addWidget(self.doctor_btn)
        self.doctor_report = QPlainTextEdit()
        self.doctor_report.setReadOnly(True)
        self.doctor_report.setStyleSheet("background: #1e1e1e; color: #00d9ff; font-family: monospace;")
        d_layout.addWidget(self.doctor_report)

        # --- TAB 4: SEARCH ---
        self.tab_search = QWidget()
        s_layout = QVBoxLayout(self.tab_search)
        search_input_layout = QHBoxLayout()
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText("Search for RPM (e.g. neovim)")
        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.clicked.connect(self.start_search)
        search_input_layout.addWidget(self.search_in)
        search_input_layout.addWidget(self.search_btn)
        s_layout.addLayout(search_input_layout)
        self.search_results = QPlainTextEdit()
        self.search_results.setReadOnly(True)
        self.search_results.setStyleSheet("background: #1e1e1e; color: #ffffff; font-family: monospace;")
        s_layout.addWidget(self.search_results)

        # --- TAB 5: UPDATER ---
        self.tab_updater = QWidget()
        u_layout = QVBoxLayout(self.tab_updater)
        self.update_btn = QPushButton("🔄 Update All Extensions")
        self.update_btn.clicked.connect(self.start_update_all)
        u_layout.addWidget(self.update_btn)
        self.update_log = QPlainTextEdit()
        self.update_log.setReadOnly(True)
        self.update_log.setStyleSheet("background: #1e1e1e; color: #ffaa00; font-family: monospace;")
        u_layout.addWidget(self.update_log)

        # Přidání záložek
        self.tabs.addTab(self.tab_manager, "Manager")
        self.tabs.addTab(self.tab_creator, "Creator")
        self.tabs.addTab(self.tab_updater, "Updater")
        self.tabs.addTab(self.tab_doctor, "Doctor")
        self.tabs.addTab(self.tab_search, "Package Search")
        main_layout.addWidget(self.tabs)

        # --- Sub-Process Setup ---
        self.build_process = QProcess(self)
        self.build_process.readyReadStandardOutput.connect(lambda: self.read_process_output(self.build_process, self.build_log))
        self.build_process.readyReadStandardError.connect(lambda: self.read_process_output(self.build_process, self.build_log))
        self.build_process.finished.connect(self.on_build_finished)

        self.search_process = QProcess(self)
        self.search_process.readyReadStandardOutput.connect(lambda: self.read_process_output(self.search_process, self.search_results))

        self.update_process = QProcess(self)
        self.update_process.readyReadStandardOutput.connect(lambda: self.read_process_output(self.update_process, self.update_log))
        self.update_process.readyReadStandardError.connect(lambda: self.read_process_output(self.update_process, self.update_log))
        self.update_process.finished.connect(self.on_update_build_finished)

        self.update_list()

    # --- Helper pro čtení z procesů ---
    def read_process_output(self, process, widget):
        out = process.readAllStandardOutput().data().decode().strip()
        err = process.readAllStandardError().data().decode().strip()
        if out: widget.appendPlainText(out)
        if err: widget.appendPlainText(err)

    # --- TAB: MANAGER ---
    def update_list(self):
        try:
            with varlink.Client(address=SOCKET_PATH) as client:
                with client.open(INTERFACE) as remote:
                    res = remote.ListExtensions()
                    self.table.setRowCount(0)
                    for e in res['extensions']:
                        row = self.table.rowCount()
                        self.table.insertRow(row)
                        self.table.setItem(row, 0, QTableWidgetItem(e['name']))
                        self.table.setItem(row, 1, QTableWidgetItem(e['version']))
                        self.table.setItem(row, 2, QTableWidgetItem(e['packages']))
        except Exception as e:
            print(f"List update failed: {e}")

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0: return
        name = self.table.item(row, 0).text()
        try:
            with varlink.Client(address=SOCKET_PATH) as client:
                with client.open(INTERFACE) as remote:
                    remote.RemoveSysext(name)
            self.update_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # --- TAB: CREATOR ---
    def start_build(self):
        name = self.name_in.text().strip()
        pkgs = self.pkgs_in.text().strip()
        if not name or not pkgs: return
        self.current_name = name
        self.build_btn.setEnabled(False)
        self.build_log.clear()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        cmd = f"toolbox run -c {CONTAINER_NAME} python3 {BUILDER_SCRIPT} {name} {pkgs}"
        self.build_process.start("bash", ["-c", cmd])

    def on_build_finished(self):
        if self.build_process.exitCode() == 0:
            self.build_log.appendPlainText("\nBuild successful. Deploying...")
            self.queue = []
            p1 = os.path.expanduser(f"~/sysext-builds/{self.current_name}.raw")
            p2 = os.path.expanduser(f"~/sysext-builds/{self.current_name}.confext.raw")
            if os.path.exists(p1): self.queue.append(p1)
            if os.path.exists(p2): self.queue.append(p2)
            self.process_deploy_queue()
        else:
            self.build_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            QMessageBox.critical(self, "Build Failed", "Check the logs.")

    def process_deploy_queue(self, force=False):
        if not self.queue:
            self.build_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.update_list()
            QMessageBox.information(self, "Success", "Deployment finished!")
            return

        self.current_path = self.queue[0]
        worker = DeployWorker(self.current_name, self.current_path, force)
        self.active_workers.append(worker) # Bezpečné uložení vlákna

        worker.finished.connect(self.on_deploy_step_done)
        worker.error.connect(self.on_deploy_error)
        worker.start()

    def cleanup_worker(self):
        worker = self.sender()
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        worker.deleteLater()

    def on_deploy_error(self, e):
        self.cleanup_worker()
        QMessageBox.critical(self, "Error", e)
        self.queue = []
        self.build_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def on_deploy_step_done(self, reply):
        self.cleanup_worker()

        status = reply.get("status")
        if status == "Success":
            self.build_log.appendPlainText(f"Deployed: {os.path.basename(self.current_path)}")
            self.queue.pop(0)
            self.process_deploy_queue()
        elif status == "ConflictFound":
            conflicts = "\n".join(reply.get("conflicts", []))
            ret = QMessageBox.warning(self, "Conflict", f"Conflicts found:\n{conflicts}\nForce?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret == QMessageBox.StandardButton.Yes:
                self.process_deploy_queue(force=True)
            else:
                self.build_log.appendPlainText("Aborted by user.")
                self.queue = []
                self.build_btn.setEnabled(True)
                self.progress_bar.setVisible(False)

    # --- TAB: DOCTOR & SEARCH ---
    def run_doctor(self):
        self.doctor_report.clear()
        self.doctor_report.appendPlainText("Scanning system for conflicts...")
        try:
            with varlink.Client(address=SOCKET_PATH) as client:
                with client.open(INTERFACE) as remote:
                    res = remote.RunDiagnostics()
                    for line in res['report']:
                        self.doctor_report.appendPlainText(line)
        except Exception as e:
            self.doctor_report.appendPlainText(f"Doctor failed: {e}")

    def start_search(self):
        query = self.search_in.text().strip()
        if not query: return
        self.search_results.clear()
        self.search_results.appendPlainText(f"Searching for '{query}'...")
        self.search_process.start("toolbox", ["run", "-c", CONTAINER_NAME, "dnf", "search", query])

    # --- TAB: UPDATER ---
    def start_update_all(self):
        self.update_log.clear()
        self.update_btn.setEnabled(False)
        self.update_queue = []

        try:
            with varlink.Client(address=SOCKET_PATH) as client:
                with client.open(INTERFACE) as remote:
                    res = remote.ListExtensions()
                    for ext in res['extensions']:
                        if ext['packages'] and ext['packages'] != "N/A":
                            self.update_queue.append(ext)
        except Exception as e:
            self.update_log.appendPlainText(f"Failed to fetch extensions: {e}")
            self.update_btn.setEnabled(True)
            return

        if not self.update_queue:
            self.update_log.appendPlainText("No updatable extensions found (missing metadata).")
            self.update_btn.setEnabled(True)
            return

        self.update_log.appendPlainText(f"Found {len(self.update_queue)} extensions to update.\n")
        self.process_update_queue()

    def process_update_queue(self):
        if not self.update_queue:
            self.update_log.appendPlainText("\n✅ All updates finished successfully!")
            self.update_btn.setEnabled(True)
            self.update_list()
            return

        self.current_update_ext = self.update_queue.pop(0)
        name = self.current_update_ext['name']
        pkgs = self.current_update_ext['packages']

        self.update_log.appendPlainText(f"\n--- Rebuilding '{name}' ---")
        cmd = f"toolbox run -c {CONTAINER_NAME} python3 {BUILDER_SCRIPT} {name} {pkgs}"
        self.update_process.start("bash", ["-c", cmd])

    def on_update_build_finished(self):
        if self.update_process.exitCode() != 0:
            self.update_log.appendPlainText(f"❌ Build failed for {self.current_update_ext['name']}. Skipping.")
            self.process_update_queue()
            return

        name = self.current_update_ext['name']
        self.update_log.appendPlainText(f"Build successful. Deploying {name}...")

        self.updater_deploy_queue = []
        p1 = os.path.expanduser(f"~/sysext-builds/{name}.raw")
        p2 = os.path.expanduser(f"~/sysext-builds/{name}.confext.raw")
        if os.path.exists(p1): self.updater_deploy_queue.append(p1)
        if os.path.exists(p2): self.updater_deploy_queue.append(p2)

        self.process_updater_deploy_queue()

    def process_updater_deploy_queue(self):
        if not self.updater_deploy_queue:
            self.process_update_queue()
            return

        path = self.updater_deploy_queue[0]
        name = self.current_update_ext['name']

        worker = DeployWorker(name, path, force=True)
        self.active_workers.append(worker) # Bezpečné uložení vlákna

        worker.finished.connect(self.on_updater_deploy_done)
        worker.error.connect(self.on_updater_deploy_error)
        worker.start()

    def on_updater_deploy_error(self, e):
        self.cleanup_worker()
        self.update_log.appendPlainText(f"❌ Deploy error: {e}")
        self.updater_deploy_queue.pop(0)
        self.process_updater_deploy_queue()

    def on_updater_deploy_done(self, reply):
        self.cleanup_worker()

        status = reply.get("status")
        if status == "Success":
            self.update_log.appendPlainText(f"Successfully deployed layer.")
        else:
            self.update_log.appendPlainText(f"Deploy warning: {status}")

        self.updater_deploy_queue.pop(0)
        self.process_updater_deploy_queue()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SysextManagerGUI()
    window.show()
    sys.exit(app.exec())
