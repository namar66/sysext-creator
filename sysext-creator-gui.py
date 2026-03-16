#!/usr/bin/python3

# Sysext-Creator GUI v13.4 - Signal Fix & Synchronous Worker
# Environment: Host System (User)

import sys
import os
import varlink
import subprocess
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel,
                             QPushButton, QMessageBox, QListWidget, QHBoxLayout,
                             QLineEdit, QProgressBar, QTabWidget, QPlainTextEdit)
from PyQt6.QtCore import QThread, pyqtSignal, QProcess

class DeployWorker(QThread):
    progress_update = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, socket_path, name, path):
        super().__init__()
        self.socket_path, self.name, self.path = socket_path, name, path

    def run(self):
        try:
            with varlink.Client(address=self.socket_path) as client:
                with client.open('io.sysext.creator') as remote:
                    # Synchronní volání démona (žádné streamování)
                    reply = remote.DeploySysext(self.name, self.path)
                    self.progress_update.emit(reply['progress'], reply['status'])
            self.finished.emit(True, f"Deployed: {os.path.basename(self.path)}")
        except Exception as e:
            self.finished.emit(False, str(e))

class SysextClientWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.socket_path = "unix:/run/sysext-creator.sock"
        self.container_name = "sysext-creator-builder-fc43" # Zkontroluj název toolboxu
        self.builder_script = os.path.expanduser("~/.local/bin/sysext-builder")
        self.is_deploying = False # Pojistka proti vícenásobnému spuštění
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Sysext Manager v13.4")
        self.setMinimumSize(850, 650)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- TAB: MANAGER ---
        self.tab_manager = QWidget()
        m_layout = QVBoxLayout(self.tab_manager)
        self.ext_list = QListWidget()
        m_layout.addWidget(QLabel("Active Layers (systemd-sysext):"))
        m_layout.addWidget(self.ext_list)
        btn_l = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self.update_list)
        self.rem_btn = QPushButton("Remove Selected")
        self.rem_btn.clicked.connect(self.remove_selected)
        btn_l.addWidget(self.refresh_btn)
        btn_l.addWidget(self.rem_btn)
        m_layout.addLayout(btn_l)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        m_layout.addWidget(self.progress_bar)

        # --- TAB: CREATOR ---
        self.tab_creator = QWidget()
        c_layout = QVBoxLayout(self.tab_creator)
        self.pkgs_in = QLineEdit()
        self.pkgs_in.setPlaceholderText("e.g. mc htop")
        c_layout.addWidget(QLabel("Build new extension (via Toolbox):"))
        c_layout.addWidget(self.pkgs_in)
        self.build_btn = QPushButton("Build & Deploy")
        self.build_btn.clicked.connect(self.start_build)
        c_layout.addWidget(self.build_btn)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("background: #000; color: #0f0; font-family: monospace;")
        c_layout.addWidget(self.output)

        self.tabs.addTab(self.tab_manager, "Manager")
        self.tabs.addTab(self.tab_creator, "Creator")
        layout.addWidget(self.tabs)

        # QProcess setup (Připojeno POUZE JEDNOU při startu aplikace)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_output)
        self.process.finished.connect(self.on_build_finished)

        self.update_list()

    def read_output(self):
        data = self.process.readAllStandardOutput().data().decode().strip()
        if not data: data = self.process.readAllStandardError().data().decode().strip()
        if data: self.output.appendPlainText(data)

    def update_list(self):
        try:
            with varlink.Client(address=self.socket_path) as client:
                with client.open('io.sysext.creator') as remote:
                    res = remote.ListExtensions()
                    self.ext_list.clear()
                    for e in res['extensions']:
                        self.ext_list.addItem(f"{e['name']}  |  v{e['version']}  |  [{e['packages']}]")
        except: pass

    def start_build(self):
        pkgs = self.pkgs_in.text().strip()
        if not pkgs: return
        self.current_name = pkgs.split()[0]
        self.build_btn.setEnabled(False)
        self.output.clear()
        self.tabs.setCurrentWidget(self.tab_creator)

        cmd = f"toolbox run -c {self.container_name} python3 {self.builder_script} {self.current_name} {pkgs}"
        self.process.start("bash", ["-c", cmd])

    def on_build_finished(self):
        self.build_btn.setEnabled(True)
        if self.process.exitCode() == 0:
            self.output.appendPlainText("\nBuild done. Starting deployment...")
            self.queue = []
            p1 = os.path.expanduser(f"~/sysext-builds/{self.current_name}.raw")
            p2 = os.path.expanduser(f"~/sysext-builds/{self.current_name}.confext.raw")
            if os.path.exists(p1): self.queue.append(p1)
            if os.path.exists(p2): self.queue.append(p2)

            self.is_deploying = True # Zamykáme frontu
            self.process_queue()
        else:
            QMessageBox.critical(self, "Build Error", "Toolbox process failed. Check the logs.")

    def process_queue(self):
        # Pokud se zrovna nic nenasazuje, ignoruj zbloudilé volání
        if not self.is_deploying: return

        if not self.queue:
            self.is_deploying = False # Odemkneme frontu
            self.progress_bar.setVisible(False)
            self.update_list()
            QMessageBox.information(self, "Success", "All layers deployed successfully!")
            return

        path = self.queue.pop(0)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0) # "Nekonečný" točící se progress bar

        self.worker = DeployWorker(self.socket_path, self.current_name, path)
        self.worker.progress_update.connect(lambda p, m: self.progress_bar.setRange(0, 100) if p == 100 else None)
        self.worker.finished.connect(self.on_step_done)
        self.worker.start()

    def on_step_done(self, success, msg):
        self.output.appendPlainText(msg)
        if success:
            self.process_queue()
        else:
            self.is_deploying = False
            self.progress_bar.setVisible(False)
            QMessageBox.critical(self, "Deployment Error", msg)

    def remove_selected(self):
        item = self.ext_list.currentItem()
        if item:
            name = item.text().split("  |  ")[0].strip()
            try:
                with varlink.Client(address=self.socket_path) as client:
                    with client.open('io.sysext.creator') as remote:
                        remote.RemoveSysext(name)
                self.update_list()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to remove: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SysextClientWindow()
    win.show()
    sys.exit(app.exec())
