Name:           fake-package-simple
Version:        1.0
Release:        2%{?dist}
Summary:        Simple test package for Sysext-Creator
License:        MIT
BuildArch:      noarch

%description
A simple test package containing only one fake binary. Used for E2E testing.

%install
mkdir -p %{buildroot}/usr/bin
echo '#!/bin/bash' > %{buildroot}/usr/bin/fake-package-simple
echo 'echo "Jsem jednoduchy fake balicek!"' >> %{buildroot}/usr/bin/fake-package-simple
chmod +x %{buildroot}/usr/bin/fake-package-simple

%files
/usr/bin/fake-package-simple

%changelog
* Fri Mar 13 2026 Martin Naď <namar66@gmail.com> - 1.0-1
- Initial test package
