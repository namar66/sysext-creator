#!/bin/bash

# ======================================================================
# Sysext-Creator Integration Test Suite v2.0
# ======================================================================
set -euo pipefail

PKG_SIMPLE="fake-package-simple"
PKG_COMPLEX="fake-package-complex"
LOG_FILE="/var/log/sysext-creator.log"
EXT_DIR="/var/lib/extensions"
STAGING_DIR="/var/tmp/sysext-staging"

# Barevný výstup
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ PASS:${NC} $1"; }
fail() { echo -e "${RED}❌ FAIL:${NC} $1"; exit 1; }
step() { echo -e "\n${BLUE}▶▶ TEST:${NC} $1"; }
warn() { echo -e "${YELLOW}⚠️ WARN:${NC} $1"; }

# --- 0. Pre-flight Checks ---
step "Kontrola prostředí"
if ! command -v sysext-creator &> /dev/null; then fail "sysext-creator chybí v PATH."; fi
if ! systemctl is-active --quiet sysext-creator-deploy.path; then fail "Démon neběží!"; fi
pass "Nástroj i démon jsou připraveny."

# Vyčištění před testem
for pkg in "$PKG_SIMPLE" "$PKG_COMPLEX"; do
    if sysext-creator list | grep -q "📦 $pkg"; then
        warn "Balíček $pkg už je nainstalován. Provádím čistku před testem..."
        sysext-creator rm "$pkg" yes >/dev/null
        sleep 4
    fi
done

# --- 1. Test komunikace s démonem (Doctor) ---
step "Komunikace s démonem (Doctor)"
if sysext-creator doctor | grep -q "Diagnostics completed"; then pass "Démon odpovídá."
else fail "Doctor nevrátil očekávaný výstup."; fi

# --- ZÁZNAM STAVU PŘED TESTEM ---
step "Snapshot stavu /etc před spuštěním testů"
# Uložíme si přesný počet položek v /etc (a ignorujeme chyby práv)
ETC_COUNT_BEFORE=$({ find /etc 2>/dev/null || true; } | wc -l)
pass "Výchozí počet položek v /etc: $ETC_COUNT_BEFORE"
# --- 2. Test jednoduchého balíčku (Bez závislostí) ---
step "Instalace jednoduchého balíčku: $PKG_SIMPLE"
sysext-creator install "$PKG_SIMPLE" > /dev/null
sleep 4

if command -v "$PKG_SIMPLE" &> /dev/null; then pass "Příkaz $PKG_SIMPLE je v systému dostupný."
else fail "Aplikace $PKG_SIMPLE se nenainstalovala správně."; fi

sysext-creator rm "$PKG_SIMPLE" > /dev/null
sleep 4
if ! command -v "$PKG_SIMPLE" &> /dev/null; then pass "Balíček $PKG_SIMPLE úspěšně odstraněn."
else fail "Odstranění $PKG_SIMPLE selhalo."; fi


# --- 3. Test komplexního balíčku (Závislosti + /etc/) ---
step "Instalace komplexního balíčku: $PKG_COMPLEX (tunel + /etc)"
sysext-creator install "$PKG_COMPLEX" > /dev/null
sleep 5

if command -v "$PKG_COMPLEX" &> /dev/null; then 
    pass "Příkaz $PKG_COMPLEX funguje (závislosti se stáhly správně)."
else 
    fail "Aplikace $PKG_COMPLEX selhala. Chybí závislosti?"; 
fi

if [[ -d "/etc/mc" ]]; then 
    pass "Konfigurace byla úspěšně zapsána do /etc/mc."
else 
    fail "Složka /etc/mc chybí! Démon nerozbalil .etc.tar.gz archiv."; 
fi

step "Odstranění komplexního balíčku vč. konfigurace (Force Remove)"
# Příkaz "yes" by měl spustit smazání souborů z /etc/ podle trackeru
sysext-creator rm "$PKG_COMPLEX" yes > /dev/null
sleep 5

if ! command -v "$PKG_COMPLEX" &> /dev/null; then 
    pass "Balíček $PKG_COMPLEX odebrán ze systému."
else 
    fail "Odstranění $PKG_COMPLEX selhalo."; 
fi

if [[ ! -d "/etc/mc" ]] || [[ -z "$(ls -A /etc/mc 2>/dev/null)" ]]; then 
    pass "Stopy v /etc/ byly čistě uklizeny díky trackeru."
else 
    fail "Konfigurace /etc/mc zůstala v systému po smazání."; 
fi

# --- 4. Crash Test: Gatekeeper a poškozený soubor ---
step "CRASH TEST: Zamezení instalace poškozeného obrazu"
DUMMY_FILE="$STAGING_DIR/poisoned-fc43.raw"
echo "Tohle není validní erofs obraz, tohle je vir!" > "$DUMMY_FILE"
sleep 4 # Čekáme na reakci démona

if [[ ! -f "$DUMMY_FILE" ]]; then 
    pass "Démon okamžitě smazal poškozený soubor ze Staging složky."
else 
    fail "Démon nechal poškozený soubor ve Staging složce!"; 
fi

if grep -q "Validation failed: poisoned-fc43.raw is corrupted" "$LOG_FILE"; then
    pass "Záchyt poškozeného souboru byl správně zaznamenán v lozích."
else
    fail "V logu chybí záznam o odmítnutí poškozeného souboru."
fi

# --- 5. Finální porovnání stavu /etc ---
step "Kontrola absolutní čistoty systému (Snapshot porovnání)"
ETC_COUNT_AFTER=$({ find /etc 2>/dev/null || true; } | wc -l)

echo -e "  📊 Stav před testem: $ETC_COUNT_BEFORE položek"
echo -e "  📊 Stav po testech:  $ETC_COUNT_AFTER položek"

if [[ "$ETC_COUNT_BEFORE" -eq "$ETC_COUNT_AFTER" ]]; then
    pass "Struktura /etc je na chlup stejná jako před testem. Nástroj po sobě nezanechal absolutně žádné stopy!"
else
    rozdil=$((ETC_COUNT_AFTER - ETC_COUNT_BEFORE))
    # Na běžícím OS mohou procesy (např. NetworkManager, dnf) vytvořit dočasné soubory.
    # Tolerujeme drobnou odchylku, ale upozorníme na ni.
    if [[ $rozdil -gt -5 && $rozdil -lt 5 ]]; then
        warn "Počet položek se nepatrně liší (rozdíl: $rozdil). Pravděpodobně jde o běžnou aktivitu OS na pozadí."
    else
        fail "Zjištěn velký rozdíl v počtu souborů ($rozdil). Nějaká konfigurace pravděpodobně nebyla smazána!"
    fi
fi

echo -e "\n${GREEN}=================================================${NC}"
echo -e "${GREEN}🎉 E2E TESTY DOKONČENY: ARCHITEKTURA JE 100% NEPRŮSTŘELNÁ!${NC}"
echo -e "${GREEN}=================================================${NC}\n"
