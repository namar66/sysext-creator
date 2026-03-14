Name:           fake-package-complex
Version:        1.0
Release:        2%{?dist}
Summary:        Complex test package with config and dependencies
License:        MIT
BuildArch:      noarch
# TADY JE TA MAGIE:
Requires:       fake-package-simple

%description
A complex test package containing a binary and /etc configuration files.
It also depends on fake-package-simple to test dependency resolution and multi-package image building.

%install
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/etc/fake-complex

echo '#!/bin/bash' > %{buildroot}/usr/bin/fake-package-complex
echo 'echo "Jsem komplexni fake balicek s konfiguraci!"' >> %{buildroot}/usr/bin/fake-package-complex
chmod +x %{buildroot}/usr/bin/fake-package-complex

echo 'TEST_VAR=123' > %{buildroot}/etc/fake-complex/config.conf
echo 'MOCK_DATA=true' > %{buildroot}/etc/fake-complex/mock.ini

%files
/usr/bin/fake-package-complex
%dir /etc/fake-complex
%config(noreplace) /etc/fake-complex/config.conf
%config(noreplace) /etc/fake-complex/mock.ini

%changelog
* Fri Mar 13 2026 Martin Naď <namar66@gmail.com> - 1.0-1
- Initial test package
