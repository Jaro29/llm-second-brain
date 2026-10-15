#!/usr/bin/env python3
"""Podpina maszynę pod wspólne zasoby agentów z vaultu. Uruchamiać po `git pull`, na każdej maszynie.

1. Skille Hermesa z 90-meta/hermes/skills/ przez `skills.external_dirs`. Lokalna kopia o tej samej nazwie
   WYGRYWA z wersją z vaultu, więc identyczne kopie idą do backupu, a różne zostają do ręcznego połączenia.
2. Linki do zasad globalnych (90-meta/CLAUDE-globalny.md): ~/AGENTS.md (Hermes), ~/.codex/AGENTS.md,
   ~/.claude/CLAUDE.md; dwa ostatnie tylko, gdy narzędzie jest zainstalowane (katalog istnieje).
3. Pluginy Hermesa z 90-meta/hermes/plugins/: symlink w ~/.hermes/plugins/, włączenie w config.yaml,
   dla run-in-terminal linijka integracji w ~/.zshrc.
Bez --wykonaj tylko raport. Backup: ~/.hermes/podepnij-backup/<data>/. Kod wyjścia 2: jest coś do ręcznego
połączenia (skrypt tego nie rusza).

    python3 ~/SecondBrain/90-meta/hermes/podepnij.py [--wykonaj]
"""
import argparse
import datetime
import filecmp
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
VAULT_SKILLS, VAULT_PLUGINS = HERE / 'skills', HERE / 'plugins'
GLOBAL = HERE.parent / 'CLAUDE-globalny.md'
HOME = Path.home()
HERMES_HOME = Path(os.environ.get('HERMES_HOME', HOME / '.hermes'))
LOCAL_SKILLS, LOCAL_PLUGINS = HERMES_HOME / 'skills', HERMES_HOME / 'plugins'
BACKUP = HERMES_HOME / 'podepnij-backup' / datetime.date.today().isoformat()
ZSH_LINE = ('[[ -r ~/.hermes/plugins/run-in-terminal/shell/run-in-terminal.zsh ]] && '
            'source ~/.hermes/plugins/run-in-terminal/shell/run-in-terminal.zsh')
IGNORE = ['__pycache__', '.DS_Store']


def rozne_pliki(a, b):
    """Ścieżki względne plików, które różnią się albo są tylko po jednej stronie."""
    out = []

    def walk(c, prefix=''):
        out.extend(prefix + n for n in c.left_only + c.right_only + c.diff_files + c.funny_files)
        for name, sub in c.subdirs.items():
            walk(sub, prefix + name + '/')
    walk(filecmp.dircmp(a, b, ignore=IGNORE))
    return sorted(out)


def do_backupu(path, sekcja):
    # Nazwa z pełną ścieżką względem domu: ~/AGENTS.md i ~/.codex/AGENTS.md nie mogą się nadpisać.
    try:
        rel = path.relative_to(HOME)
    except ValueError:
        rel = Path(*path.parts[1:])
    dest = BACKUP / sekcja / str(rel).replace('/', '__')
    if dest.exists() or dest.is_symlink():
        dest = dest.with_name(dest.name + '.' + datetime.datetime.now().strftime('%H%M%S%f'))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def config_text():
    cfg = HERMES_HOME / 'config.yaml'
    return cfg.read_text(encoding='utf-8') if cfg.is_file() else ''


def hermes(*args):
    sys.stdout.flush()  # żeby raport nie wymieszał się z wyjściem hermesa
    subprocess.run(['hermes', *args], check=True)


def skille(wykonaj):
    print('\n[1] Skille (skills.external_dirs)')
    ustawione = str(VAULT_SKILLS) in config_text()
    print(f'  external_dirs -> vault: {"tak" if ustawione else "NIE"}')
    konflikty = 0
    for skill in sorted(d for d in VAULT_SKILLS.iterdir() if (d / 'SKILL.md').is_file()):
        kopie = [p.parent for p in LOCAL_SKILLS.rglob('SKILL.md') if p.parent.name == skill.name
                 and not any(x.startswith('.') for x in p.relative_to(LOCAL_SKILLS).parts)]
        if not kopie:
            print(f'  {skill.name}: OK (brak lokalnej kopii)')
        for kopia in kopie:
            roznice = rozne_pliki(kopia, skill)
            if roznice:
                konflikty += 1
                print(f'  {skill.name}: RÓŻNA lokalna kopia - połącz ręcznie: diff -ru {kopia} {skill} '
                      f'({", ".join(roznice[:6])})')
            elif wykonaj:
                print(f'  {skill.name}: identyczna kopia przeniesiona do {do_backupu(kopia, "skills")}')
            else:
                print(f'  {skill.name}: identyczna lokalna kopia {kopia}, do przeniesienia')
    if wykonaj and not ustawione:
        hermes('config', 'set', 'skills.external_dirs', f'["{VAULT_SKILLS}"]')
    return konflikty


def linki(wykonaj):
    print('\n[2] Zasady globalne (linki do 90-meta/CLAUDE-globalny.md)')
    for link in (HOME / 'AGENTS.md', HOME / '.codex/AGENTS.md', HOME / '.claude/CLAUDE.md'):
        if not link.parent.is_dir():
            print(f'  {link}: pominięty (brak {link.parent}, narzędzie niezainstalowane)')
            continue
        if link.is_symlink() and link.resolve() == GLOBAL:
            print(f'  {link}: OK')
            continue
        stan = 'zwykły plik' if link.exists() or link.is_symlink() else 'brak'
        if not wykonaj:
            print(f'  {link}: {stan}, do podlinkowania')
            continue
        if link.exists() or link.is_symlink():
            print(f'  {link}: stary plik przeniesiony do {do_backupu(link, "linki")}')
        link.symlink_to(GLOBAL)
        print(f'  {link}: podlinkowany')


def pluginy(wykonaj):
    print('\n[3] Pluginy Hermesa')
    konflikty = 0
    for plugin in sorted(d for d in VAULT_PLUGINS.iterdir() if (d / 'plugin.yaml').is_file()):
        local = LOCAL_PLUGINS / plugin.name
        if local.is_symlink() and local.resolve() == plugin:
            print(f'  {plugin.name}: OK (symlink do vaultu)')
        elif local.exists() and not local.is_symlink() and rozne_pliki(local, plugin):
            konflikty += 1
            print(f'  {plugin.name}: RÓŻNA lokalna wersja - połącz ręcznie: diff -ru {local} {plugin}')
            continue
        elif not wykonaj:
            print(f'  {plugin.name}: {"identyczna kopia" if local.exists() else "brak"}, do podlinkowania')
        else:
            if local.exists() or local.is_symlink():
                print(f'  {plugin.name}: stara kopia przeniesiona do {do_backupu(local, "plugins")}')
            LOCAL_PLUGINS.mkdir(parents=True, exist_ok=True)
            local.symlink_to(plugin)
            print(f'  {plugin.name}: podlinkowany')
        if f'- {plugin.name}' not in config_text():
            if wykonaj:
                hermes('plugins', 'enable', plugin.name)
            else:
                print(f'  {plugin.name}: niewłączony w config.yaml, do włączenia')
        if plugin.name == 'run-in-terminal':
            zshrc = HOME / '.zshrc'
            if not zshrc.is_file():
                print('  run-in-terminal: brak ~/.zshrc - integracja zsh pominięta (zostaje tryb "nowe okno")')
            elif 'run-in-terminal.zsh' in zshrc.read_text(encoding='utf-8'):
                print('  run-in-terminal: integracja zsh w ~/.zshrc OK')
            elif wykonaj:
                BACKUP.mkdir(parents=True, exist_ok=True)
                shutil.copy2(zshrc, BACKUP / 'zshrc')
                with zshrc.open('a', encoding='utf-8') as f:
                    f.write('\n# Hermes ▶ (plugin run-in-terminal): uruchamianie komend z czatu w tym terminalu\n'
                            + ZSH_LINE + '\n')
                print('  run-in-terminal: dopisano integrację na końcu ~/.zshrc (przenieś ją za p10k, '
                      'przed autosuggestions/syntax-highlighting)')
            else:
                print('  run-in-terminal: brak integracji w ~/.zshrc, do dopisania')
    return konflikty


def unit_text():
    return ('[Unit]\nDescription=Second Brain: git pull i stan vaultu po zalogowaniu\n'
            'After=graphical-session.target\n\n'
            '[Service]\nType=oneshot\n'
            f'ExecStart=/usr/bin/python3 {HERE / "vault-start.py"}\n\n'
            '[Install]\nWantedBy=graphical-session.target\n')


def usluga(wykonaj):
    print('\n[4] Start sesji (vault-start.service: git pull i powiadomienie)')
    unit = HOME / '.config/systemd/user/vault-start.service'
    if not shutil.which('systemctl'):
        print('  pominięte: brak systemctl')
        return
    aktualny = unit.is_file() and unit.read_text(encoding='utf-8') == unit_text()
    wlaczony = subprocess.run(['systemctl', '--user', 'is-enabled', 'vault-start.service'],
                              capture_output=True, text=True).stdout.strip() == 'enabled'
    if aktualny and wlaczony:
        print('  vault-start.service: OK')
        return
    if not wykonaj:
        print(f'  vault-start.service: {"nieaktualny" if unit.is_file() else "brak"}'
              f'{"" if wlaczony else ", niewłączony"}, do instalacji')
        return
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(unit_text(), encoding='utf-8')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', 'vault-start.service'], check=True, capture_output=True)
    print('  vault-start.service: zainstalowany i włączony (zadziała przy następnym logowaniu; '
          'test teraz: systemctl --user start vault-start; dziennik: journalctl --user -u vault-start)')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--wykonaj', action='store_true', help='wprowadź zmiany (domyślnie tylko raport)')
    a = p.parse_args()
    try:
        wersja = subprocess.run(['hermes', '--version'], capture_output=True, text=True).stdout.splitlines()[0]
    except (OSError, IndexError):
        wersja = 'nie znaleziono polecenia hermes'
    print(f'Hermes: {wersja}')
    konflikty = skille(a.wykonaj)
    linki(a.wykonaj)
    konflikty += pluginy(a.wykonaj)
    usluga(a.wykonaj)
    if a.wykonaj:
        print('\nRęcznie: restart aplikacji Hermes (backend pluginów), potem Capabilities - Plugins - Rescan '
              'i włączenie przełącznika run-in-terminal. Sprawdź: skill_view("second-brain-vault") ma '
              f'_source_path w vaulcie. Wycofanie: pliki z {BACKUP} z powrotem na miejsce.')
    if konflikty:
        print(f'\n{konflikty} pozycji do ręcznego połączenia; skrypt ich nie rusza.')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
