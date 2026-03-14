Name:           fake-package-simple
Version:        1.0
Release:        2%{?dist}
Summary:        Simple test package for Sysext-Creator
License:        GPLv2
BuildArch:      noarch

%description
A simple test package containing only one fake binary. Used for E2E testing.

%install
mkdir -p %{buildroot}%{_bindir}
echo '#!/bin/bash' > %{buildroot}%{_bindir}/fake-package-simple
echo 'echo "I am a simple fake package!"' >> %{buildroot}%{_bindir}/fake-package-simple
chmod +x %{buildroot}%{_bindir}/fake-package-simple

%files
%{_bindir}/fake-package-simple

%changelog
* Fri Mar 13 2026 Martin Naď <namar66@gmail.com> - 1.0-1
- Initial test package
