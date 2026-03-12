%bcond_without deps
Name:           sysext-creator
Version:        2.0.0
Release:        1%{?dist}
Summary:        Správce systémových rozšíření pro Fedoru Kinoite/Silverblue

License:        MIT
URL:            https://github.com/tvoje-jmeno/sysext-creator
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  systemd-rpm-macros
BuildRequires:	desktop-file-utils
BuildRequires:	libappstream-glib
# Závislosti, které musí hostitelský systém mít (aby fungovalo GUI a wrapper)
Requires:       libnotify

%description
Grafický a CLI správce pro tvorbu, nasazování a správu atomických systémových
rozšíření (systemd-sysext) pomocí kontejnerů Distrobox.


%package kinoite
Summary: GUI for sysext-creator
BuildArch:      noarch
%if %{with deps}
Requires:       python3-pyqt6
Requires: %{name} = %{version}-%{release}
%endif
%description kinoite
This package contains KDE GUI integration
%prep
%setup -q

%build
# Jedná se o bash a python skripty, není potřeba nic kompilovat.

%install
rm -rf $RPM_BUILD_ROOT

# 1. HLAVNÍ NÁSTROJE (Wrapper, Core, GUI)
install -D -m 755 sysext-creator.sh %{buildroot}%{_bindir}/sysext-creator
install -D -m 755 sysext-creator-core.sh %{buildroot}%{_bindir}/sysext-creator-core
install -D -m 755 sysext-gui %{buildroot}%{_bindir}/sysext-gui
install -D -m 755 setup-raw.sh %{buildroot}%{_bindir}/sysext-creator-setup
install -D -m 755 sysext-gui-wrapper-gui.sh %{buildroot}%{_bindir}/sysext-gui-wrapper
# 2. DÉMON (Logika pro práva roota)
# Standardně démoni nepatří do /usr/bin, ale do libexec
install -D -m 755 sysext-creator-deploy.sh %{buildroot}%{_libexecdir}/%{name}/sysext-creator-deploy

# 3. SYSTEMD UNITS (Musí jít do /usr/lib/systemd/..., NE do /etc/!)
install -D -m 644 sysext-creator-deploy.service %{buildroot}%{_unitdir}/sysext-creator-deploy.service
install -D -m 644 sysext-creator-deploy.path %{buildroot}%{_unitdir}/sysext-creator-deploy.path

# 4. DESKTOP INTEGRACE
# Zástupce pro GUI aplikaci
install -D -m 644 sysext-creator.desktop %{buildroot}%{_datadir}/applications/sysext-creator.desktop
# Ikona do správné hicolor složky (aby ji KDE hned našlo i z .raw obrazu)
install -D -m 644 sysext-creator-icon.png %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/sysext-creator-icon.png
# Dolphin Service Menu
install -D -m 644 sysext-install.desktop %{buildroot}%{_datadir}/kio/servicemenus/sysext-install.desktop

# 5. BASH COMPLETION
install -D -m 644 bash-completion %{buildroot}%{_datadir}/bash-completion/completions/sysext-creator
install -D -m 644 sysext-update.service $RPM_BUILD_ROOT/usr/lib/systemd/user/sysext-update.service
install -D -m 644 sysext-update.timer $RPM_BUILD_ROOT/usr/lib/systemd/user/sysext-update.timer
mkdir -p %{buildroot}%{_datadir}/metainfo
install -D -m 644 sysext-creator.metainfo.xml %{buildroot}%{_metainfodir}

%check
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/*.metainfo.xml
desktop-file-validate %{buildroot}%{_datadir}/applications/*.desktop

%post
# Zaregistruje a spustí systemd path unit po instalaci balíčku
%systemd_post sysext-creator-deploy.path

%preun
# Zastaví démony před odinstalací
%systemd_preun sysext-creator-deploy.path
%systemd_preun sysext-creator-deploy.service

%postun
%systemd_postun_with_restart sysext-creator-deploy.path

%files
# Zde deklarujeme, že všechny tyto soubory balíček vlastní
%{_bindir}/sysext-creator
%{_bindir}/sysext-creator-core
%{_bindir}/sysext-creator-setup
%{_libexecdir}/%{name}/sysext-creator-deploy
%{_unitdir}/sysext-creator-deploy.service
%{_unitdir}/sysext-creator-deploy.path
%{_datadir}/bash-completion/completions/sysext-creator
%{_userunitdir}/sysext-update.service
%{_userunitdir}/sysext-update.timer
%{_metainfodir}/*.metainfo.xml
%files kinoite
%{_bindir}/sysext-gui
%{_bindir}/sysext-gui-wrapper
%{_datadir}/applications/sysext-creator.desktop
%{_datadir}/icons/hicolor/512x512/apps/sysext-creator-icon.png
%{_datadir}/kio/servicemenus/sysext-install.desktop

%changelog
* Tue Mar 10 2026 Martin Naď <namar66@gmail.com> - 2.0.0-1
- update pure podman version
- bug fixes

* Tue Mar 10 2026 Martin Naď <namar66@gmail.com> - 1.6.2-1
- add basic inspect function doctor

* Mon Mar 09 2026 Martin Naď <namar66@gmail.com> - 1.6.1-1
- fix bugs
* Mon Mar 09 2026 Martin Naď <namar66@gmail.com> - 1.6.0-1
- Added Auto-Healer: automatic recovery of the tool after Fedora upgrade.
- Image versioning: full compatibility with systemd-sysext (-fcXX.raw format).
- Improved GUI: dynamic detection of versioned images and smoother operation.
- Stability: fixed SELinux contexts for services and fixed pipefail error in daemon.
- Maintenance: added complete and safe uninstall option.
- Optimization: smart skipping of updates for local packages and handling of non-existent files when deleting.

* Sun Mar 08 2026 Tvoje Jmeno <email@example.com> - 1.5.0-1
- Initial RPM package release for Atomic Fedora
