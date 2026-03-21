#!/usr/bin/python3

# Sysext-Creator GUI v3.1 - Thread Safe & Metadata Aware
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
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"

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
        self.active_workers = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Sysext Creator Pro v4.2")
        self.setMinimumSize(1000, 700)
        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- TAB 1: MANAGER ---
        self.tab_manager = QWidget()
        m_layout = QVBoxLayout(self.tab_manager)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Version", "Packages"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        self.name_in.setPlaceholderText("Extension name")
        self.pkgs_in = QLineEdit()
        self.pkgs_in.setPlaceholderText("Packages (e.g. htop nmap)")
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

        self.tabs.addTab(self.tab_manager, "Manager")
        self.tabs.addTab(self.tab_creator, "Creator")
        main_layout.addWidget(self.tabs)

        self.build_process = QProcess(self)
        self.build_process.readyReadStandardOutput.connect(self.read_output)
        self.build_process.finished.connect(self.on_build_finished)

        self.update_list()

    def read_output(self):
        out = self.build_process.readAllStandardOutput().data().decode()
        self.build_log.appendPlainText(out.strip())

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
        except: pass

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0: return
        name = self.table.item(row, 0).text()
        try:
            with varlink.Client(address=SOCKET_PATH) as client:
                with client.open(INTERFACE) as remote:
                    remote.RemoveSysext(name)
            self.update_list()
        except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def start_build(self):
        name = self.name_in.text().strip()
        pkgs = self.pkgs_in.text().strip()
        if not name or not pkgs: return
        self.current_name = name
        self.build_btn.setEnabled(False)
        self.build_log.clear()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        # Cesta k builderu přes /run/host
        script = "/run/host" + BUILDER_SCRIPT
        self.build_process.start("toolbox", ["run", "-c", CONTAINER_NAME, "python3", script, name, *pkgs.split()])

    def on_build_finished(self):
        self.progress_bar.setVisible(False)
        self.build_btn.setEnabled(True)
        if self.build_process.exitCode() == 0:
            path = f"/var/tmp/sysext-creator/{self.current_name}.raw"
            self.worker = DeployWorker(self.current_name, path)
            self.worker.finished.connect(self.on_deploy_done)
            self.worker.start()
        else:
            QMessageBox.critical(self, "Error", "Build failed.")

    def on_deploy_done(self, reply):
        if reply.get("status") == "Success":
            self.update_list()
            QMessageBox.information(self, "Success", "Extension deployed!")
        else:
            QMessageBox.warning(self, "Warning", reply.get("status"))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = SysextManagerGUI()
    gui.show()
    sys.exit(app.exec())
