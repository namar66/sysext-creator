# 🚀 Sysext-Creator

**Sysext-Creator** je automatizovaný nástroj pro správu systémových rozšíření (`systemd-sysext`) na atomických distribucích (Fedora Silverblue, Kinoite). Umožňuje instalovat aplikace přímo do `/usr` bez nutnosti vrstvení (layering) přes `rpm-ostree`.

## ✨ Hlavní funkce
- **Atomické nasazení:** Aplikace běží nativně, ale systém zůstává čistý.
- **Auto-Update:** Systemd Timer automaticky aktualizuje aplikace na pozadí.
- **Chytrý Garbage Collector:** Udržuje kontejner pro aktuální verzi OS a jednu verzi zpět (N-1) pro bezpečný rollback.
- **OS Awareness:** Automaticky detekuje upgrade nebo rollback systému a přebuduje obrazy.
- **Bezpečný Sudo:** Většina operací probíhá bez nutnosti zadávat heslo díky skupině `sysext-admins`.
- **Bash Completion:** Našeptávání příkazů a balíčků přes Tabulátor.

## 🛠️ Instalace

1. Stáhni si oba skripty (`sysext-creator.sh` a `setup.sh`) do jedné složky.
2. Dej jim práva ke spuštění:
   ```bash
   chmod +x setup.sh sysext-creator.sh
   ```
3. Spusť instalaci:

    ```Bash
    ./setup.sh
    ```
Důležité: Restartuj terminál pro načtení práv skupiny sysext-admins.

📖 Použití
Instalace aplikace: 
  ```Bash
 sysext-creator install htop
  ```
Odstranění aplikace:
  ```Bash
  sysext-creator rm htop
  ```
Seznam aplikací:
```Bash
sysext-creator list
```
Ruční aktualizace všeho:
```Bash
sysext-creator update
```
Povýšení po upgradu OS:
```Bash
sysext-creator upgrade-box
```
📂 Struktura projektu
sysext-creator.sh: Hlavní engine běžící uvnitř kontejneru.

setup.sh: Instalátor, který nastavuje Systemd Timery, práva a Wrapper.
