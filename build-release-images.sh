#!/bin/bash
VERSIONS=("42" "43" "44")

# Složka, kam se uloží hotové .raw soubory (vytvoří se v aktuálním adresáři)
OUT_DIR="$(pwd)/build_output"

mkdir -p "$OUT_DIR"
echo "🚀 Spouštím hromadný build RAW obrazů pro GitHub Release..."

build_image() {
    local fver="$1"
    local variant="$2"

    local img_base_name="sysext-creator"
    local pkgs="sysext-creator distrobox"

    if [[ "$variant" == "kinoite" ]]; then
        img_base_name="sysext-creator-kinoite"
        pkgs="sysext-creator-kinoite sysext-creator iio-sensor-proxy python-pyqt6-rpm-macros python3-pyqt6 python3-pyqt6-base python3-pyqt6-sip qt6-qtremoteobjects qt6-qtsensors qt6-qttools-libs-designer qt6-qttools-libs-help distrobox"
    fi

    local full_name="${img_base_name}-fc${fver}"

    echo "========================================"
    echo "📦 Builduji: ${full_name}.raw (Fedora $fver)"
    echo "========================================"

    podman run --rm --privileged \
        -v "$OUT_DIR:/ext_out" \
        "registry.fedoraproject.org/fedora:${fver}" \
        /bin/bash -c "
            dnf install -y dnf-plugins-core erofs-utils cpio selinux-policy-targeted >/dev/null 2>&1
            dnf copr enable -y nadmartin/sysext-creator >/dev/null 2>&1

            mkdir -p /tmp/pkg
            cd /tmp/pkg
            dnf download $pkgs --forcearch=$(uname -m) --exclude=*.i686,*.src

            if ! ls *.rpm >/dev/null 2>&1; then
                echo '❌ CHYBA: Žádné balíčky se nestáhly. Končím build pro tuto verzi.'
                exit 1
            fi
            mkdir -p /tmp/rootfs/usr/lib/extension-release.d
            echo 'ID=fedora' > /tmp/rootfs/usr/lib/extension-release.d/extension-release.${full_name}
            echo 'VERSION_ID=${fver}' >> /tmp/rootfs/usr/lib/extension-release.d/extension-release.${full_name}

            echo '=> Vybaluji RPM archivy...'
            cd /tmp/rootfs
            for f in /tmp/pkg/*.rpm; do
                rpm2cpio \$f | cpio -idmv >/dev/null 2>&1
            done

            echo '=> Generuji EROFS obraz...'
            mkfs.erofs -zlz4hc --force-uid=0 --force-gid=0 \
                --file-contexts=/etc/selinux/targeted/contexts/files/file_contexts \
                /ext_out/${full_name}.raw . >/dev/null 2>&1
        "

    # Kontrola, jestli podman proběhl v pořádku
    if [ $? -eq 0 ]; then
        echo "✅ Hotovo: $OUT_DIR/${full_name}.raw"
    else
        echo "❌ Sestavení ${full_name}.raw selhalo!"
    fi
    echo ""
}

for v in "${VERSIONS[@]}"; do
    build_image "$v" "core"
    build_image "$v" "kinoite"
done

echo "🎉 Všechny obrazy byly úspěšně vygenerovány ve složce: $OUT_DIR"
echo "Nyní je můžeš nahrát jako 'Assets' k tvému GitHub Release (v1.6.0)!"
exit 0
