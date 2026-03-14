Name:           fake-package-complex
Version:        1.0
Release:        3%{?dist}
Summary:        Complex test package with config and dependencies
License:        GPLv2
BuildArch:      noarch

Requires:       fake-package-simple

%description
A complex test package containing a binary and /etc configuration files.
It also depends on fake-package-simple to test dependency resolution and multi-package image building.

%install
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_sysconfdir}/fake-complex

echo '#!/bin/bash' > %{buildroot}%{_bindir}/fake-package-complex
echo 'echo "I am a complex fake package with configuration!"' >> %{buildroot}%{_bindir}/fake-package-complex
chmod +x %{buildroot}%{_bindir}/fake-package-complex

echo 'TEST_VAR=123' > %{buildroot}%{_sysconfdir}/fake-complex/config.conf
echo 'MOCK_DATA=true' > %{buildroot}%{_sysconfdir}/fake-complex/mock.ini

%files
%{_bindir}/fake-package-complex
%dir %{_sysconfdir}/fake-complex
%config(noreplace) %{_sysconfdir}/fake-complex/config.conf
%config(noreplace) %{_sysconfdir}/fake-complex/mock.ini

%changelog
* Fri Mar 13 2026 Martin Naď <namar66@gmail.com> - 1.0-1
- Initial test package
