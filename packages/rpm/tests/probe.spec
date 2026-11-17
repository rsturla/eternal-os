Name: eternal-rpmx-probe
Version: %{probe_version}
Release: 1
Summary: Isolated package transaction test
License: MIT
BuildArch: noarch
%description
Disposable fixture used only inside an rpmx transaction root.
%install
mkdir -p %{buildroot}/usr/share/eternal-rpmx-probe %{buildroot}/etc
printf 'payload-%{version}\n' > %{buildroot}/usr/share/eternal-rpmx-probe/payload
printf 'default-%{version}\n' > %{buildroot}/etc/eternal-rpmx-probe.conf
%files
/usr/share/eternal-rpmx-probe/payload
%config(noreplace) /etc/eternal-rpmx-probe.conf
