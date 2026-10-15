---
name: taxonomy
description: Zamknięty słownik tagów dla Second Brain v2. Jedyne źródło prawdy dla klasyfikacji. Model wybiera wyłącznie z tych list.
version: 1.0
created: 2026-08-29
method: analiza treści 150 rozmów losowanych warstwowo (90 typowych, 30 z kodem, 30 długich), rozrzut po latach 2023-2026
---

# Taksonomia Second Brain v2

## Zasada nadrzędna

Model **nie ma prawa utworzyć tagu spoza tych list**. Walidacja jest mechaniczna: każde pole niżej jest enumem w schemacie JSON. Tag, którego brakuje, trafia jako propozycja do `90-meta/tag-proposals.md` wraz z identyfikatorem notatki i uzasadnieniem, i czeka na decyzję człowieka.

Pięć niezależnych osi. Nie zwijaj ich w jedną listę: pytanie "wszystkie decyzje, niezależnie od dziedziny" musi dać się zadać.

---

## Oś 1: `domains` (od 1 do 3)

O czym jest rozmowa. Jeśli pasują więcej niż trzy, wybierz trzy najważniejsze i rozważ podział rozmowy na segmenty.

### linux-config
**Sam system**, nie to, co na nim uruchamiasz: pacman, yay, AUR jako mechanizm, systemd, KDE i Wayland, shell (zsh, fish), dual-boot, partycje, btrfs, wirtualizacja (libvirt, KVM), montowanie, uprawnienia, keyring.
Nie: `arch`, `linux`, `system`, `terminal`, `wirtualizacja`.
Granice: "yay nie aktualizuje pakietu" to linux-config. "NVIDIA nie ładuje sterownika" to linux-hardware. **"Jak zainstalować IntelliJ / który odtwarzacz wideo wybrać" to aplikacje-desktop**, bo przedmiotem jest aplikacja, nie system.
**Uwaga kalibracyjna:** ten tag ma skłonność do puchnięcia jako worek na "cokolwiek robiłem na Linuksie". Jeśli po ingeście przekracza 25% notatek, sprawdź, czy nie wchłonął aplikacji, dokumentów albo promptów.

### aplikacje-desktop
Wybór, instalacja, aktualizacja i konfiguracja **konkretnych aplikacji użytkownika**: IDE, przeglądarki, odtwarzacze, menedżery haseł, klienty, narzędzia biurowe. Niezależnie od systemu.
Nie: `aplikacje`, `programy`, `software`.
Granice: "wygasła wersja IntelliJ, jak przeinstalować" to aplikacje-desktop. "IntelliJ nie startuje, bo brakuje biblioteki systemowej" to linux-config. Instalacja Claude Desktop przez AUR dostaje oba.

### linux-hardware
Warstwa sprzęt plus system: sterowniki NVIDIA, kernel, moduły, undervolting, temperatury, zasilanie, obsługa peryferiów w Linuksie (mikrofon, audio, wifi).
Nie: `nvidia`, `sterowniki`, `kernel`.
Granice: "jakie słuchawki kupić" to sprzet plus zakupy-research. "słuchawki nie działają pod Linuksem" to linux-hardware.

### windows
Wszystko po stronie Windows: rejestr, eksplorator, klucze licencyjne, skróty klawiaturowe, aplikacje Windows, przygotowanie do dual-boota od strony Windows.
Nie: `win11`, `microsoft`.
Granice: "Windows 11 w maszynie wirtualnej na Linuksie" dostaje oba: windows i linux-config.

### gaming-linux
Uruchamianie gier na Linuksie: Proton, Wine, Lutris, Heroic, Steam, GOG, antycheaty, wydajność, problemy z uruchomieniem.
Nie: `proton`, `wine`, `steam`, `gry-linux`.
Granice: "jak zbudować postać w grze" to gry. "gra nie startuje przez Heroic" to gaming-linux.

### gry
Zawartość i mechanika gier: buildy, poradniki, wiki, blueprinty, save editory, co kupić i gdzie.
Nie: `gaming`, `gamedev`.
Granice: patrz wyżej. Kryterium: czy problem zniknąłby na Windowsie. Jeśli tak, to gaming-linux.

### sprzet
Komponenty i urządzenia jako przedmiot sam w sobie: budowa PC, upgrade laptopa, monitory i telewizory, audio, peryferia, pasty termoprzewodzące, napędy.
Nie: `hardware`, `komputer`, `pc`.
Granice: sprzet opisuje, czym rzecz jest i czy warto. linux-hardware opisuje, jak ją zmusić do działania.

### zakupy-research
Research przed zakupem: ceny, opinie, recenzje, porównania modeli, gdzie kupić, kody rabatowe, odpowiedniki dostępne w Polsce.
Nie: `zakupy`, `ceny`, `shopping`.
Granice: to jest najczęstszy typ rozmowy pozatechnicznej w archiwum i prawie zawsze idzie w parze z `kind: decision`.

### java
Java jako język: składnia, OOP, strumienie, kolekcje, wyjątki, Maven, JUnit, zadania z kursu, wyjaśnianie kodu.
Nie: `javascript`, `java-core`, `programowanie`.
Granice: kod z adnotacjami Springa to spring-boot, nawet jeśli pytanie dotyczy składni.

### spring-boot
Spring Boot i ekosystem: MVC, DI, Data JPA, Hibernate, Security, konfiguracja, REST API.
Nie: `spring`, `springboot`, `hibernate`.

### bazy-danych
SQL, MySQL, PostgreSQL, H2, JPQL, schematy, migracje (Flyway, Liquibase), eksport i import danych.
Nie: `sql`, `db`, `flyway`.

### frontend
Angular, TypeScript, JavaScript, HTML, CSS, przeglądarkowa strona aplikacji.
Nie: `angular`, `js`, `web`.

### git-workflow
Git i GitHub: komendy, gałęzie, commity, stan repozytorium, rozwiązywanie konfliktów.
Nie: `git`, `github`, `wersjonowanie`.

### devops-cloud
Docker, deployment, serwery, chmura publiczna, VPS, SSH, nginx, CI.
Nie: `docker`, `oci`, `cloud`, `serwer`.
Granice: postawienie kontenera na własnym desktopie to linux-config. Postawienie go na zdalnej instancji to devops-cloud.

### ai-llm
Modele i narzędzia AI jako przedmiot: porównania modeli, limity planów, możliwości, Ollama, lokalne modele, NotebookLM, IDE z AI, wybór modelu pod sprzęt.
Nie: `ai`, `llm`, `gpt`, `sztuczna-inteligencja`.
Granice: **nie taguj tym rozmowy tylko dlatego, że prowadził ją model.** To najczęstszy fałszywy pozytyw w tym archiwum. Tag dotyczy rozmów, w których AI jest tematem.

### prompt-engineering
Pisanie i ulepszanie promptów, role systemowe, instrukcje niestandardowe, formatowanie odpowiedzi, meta-prompty.
Nie: `prompt`, `prompty`, `instrukcje`.
Granice: rozmowa zaczynająca się od "Jesteś ekspertem X" nie jest prompt-engineering. Jest o X. Tag przysługuje, gdy przedmiotem jest sam prompt.

### automatyzacja-desktop
Skrypty i narzędzia usprawniające pracę na własnej maszynie: dyktowanie i speech-to-text, ydotool, skróty klawiszowe, skrypty bash i python do zadań osobistych, automaty do plików.
Nie: `skrypty`, `bash`, `automatyzacja`.

### media-rozrywka
Filmy, seriale, gdzie obejrzeć, premiery, streaming i jego błędy, YouTube, audiobooki, muzyka.
Nie: `filmy`, `netflix`, `youtube`.

### jezyki-tlumaczenia
Nauka języków, aplikacje do nauki, tłumaczenia tekstów, napisów i piosenek, znaczenia słów.
Nie: `angielski`, `tlumaczenie`, `jezyki`.

### finanse-podatki
Podatki, rachunki, taryfy, przeliczniki walut, produkty oszczędnościowe, koszty utrzymania.
Nie: `pieniadze`, `podatki`.
**Uwaga prywatności:** ustaw `sensitive: true`. Automatyczna ekstrakcja sygnałów o użytkowniku została wycofana dla wszystkich domen.

### sprawy-lokalne
Własna okolica i sprawy codzienne z geografią: godziny otwarcia, usługi, urzędy, sklepy, komunikacja.
Nie: `miasto`, `lokalne`, `polska`.

### zdrowie
Objawy, badania, skierowania, domowe sposoby, sprzęt medyczny.
Nie: `medycyna`, `lekarz`.
**Uwaga prywatności:** jak wyżej. Zawsze `sensitive: true`.

### diy-majsterkowanie
Projekty własnoręczne: konstrukcje, modele, narzędzia, materiały, wymiary.
Nie: `diy`, `majsterkowanie`, `narzedzia`.

### sport-rekreacja
Bieganie, rower, sprzęt sportowy, wydarzenia i wyniki sportowe.
Nie: `sport`, `bieganie`.

### motoryzacja
Samochody, serwis, części, przeglądy.
Nie: `auto`, `samochod`.
**Marginalny:** w próbce 150 rozmów zero trafień. Tag utrzymany na zapas, ale jeśli po migracji ma poniżej 15 notatek, scal go z sport-rekreacja lub usuń.

### wiedza-ogolna
Jednorazowe pytania faktograficzne bez własnej dziedziny: historia, przyroda, jednostki miary, osoby publiczne, polityka, ciekawostki.
Nie: `ogolne`, `inne`, `rozne`.
**To jest worek i ma nim być.** Prawie wszystko, co tu wpada, ma `kind: reference-lookup` i `signal: 1`, czyli i tak nie awansuje do wiki. Jeśli jakiś podtemat urośnie ponad 40 notatek, wydziel mu własną domenę przy najbliższej rewizji taksonomii.

---

## Oś 2: `kind` (dokładnie 1)

Typ poznawczy: czego rozmowa próbowała dokonać. To jest oś, której nie było w pierwotnej propozycji i która daje najwięcej przy retrievalu.

| Wartość | Definicja | Sygnał rozpoznawczy |
|---|---|---|
| `reference-lookup` | jednorazowe pytanie o fakt, bez ciągu dalszego | jedna tura, brak kodu, odpowiedź zamyka temat |
| `troubleshooting` | coś nie działa, trwa diagnostyka | wklejone błędy, logi, komunikaty, iteracja |
| `how-to` | jak wykonać znaną czynność | "jak zainstalować", "jak sprawdzić", kroki |
| `decision` | wybór między opcjami | porównania, kryteria, "co lepsze", research zakupowy |
| `learning` | zrozumienie pojęcia lub nauka umiejętności | "co to znaczy", "wytłumacz", zadania z kursu |
| `build` | budowanie czegoś od zera | projekt, skrypt, konfiguracja środowiska, wiele tur |
| `code-review` | ocena istniejącego kodu lub projektu | wklejony kod plus prośba o feedback |
| `content-creation` | wytworzenie tekstu | tłumaczenie, pismo, opis, notatka, napisy |
| `meta-ai` | praca nad samym narzędziem AI | prompty, instrukcje, konfiguracja asystenta |
| `personal` | sprawa osobista lub codzienna bez wymiaru technicznego | godziny otwarcia, sprawa urzędowa, wiadomość do kogoś |

Rozstrzyganie remisów, w kolejności: `troubleshooting` bije `how-to`, gdy pojawia się błąd. `build` bije `how-to`, gdy powstaje coś nowego przez wiele tur. `decision` bije `reference-lookup`, gdy porównywane są co najmniej dwie opcje.

---

## Oś 3: `projects` (0 do 3)

Nazwane przedsięwzięcia, które ciągną się przez wiele rozmów. Pusta lista jest normalna i dotyczy większości archiwum.

| Wartość | Zakres | Okres |
|---|---|---|
| `second-brain` | ten vault: ingest, kompilacja wiki, narzędzia | 2026 |
| `hermes-agent` | agent AI korzystający z vaultu, jego skille i wdrożenie | 2026 |
| `przykladowy-projekt` | miejsce na własny projekt; zastąp nazwami swoich przedsięwzięć | 2026 |

Nowy projekt dodaje wyłącznie człowiek. Model, który widzi powtarzalne przedsięwzięcie bez tagu, zgłasza je do `tag-proposals.md`.

---

## Oś 4: `status` (dokładnie 1)

| Wartość | Znaczenie |
|---|---|
| `resolved` | problem rozwiązany, rozmowa domknięta |
| `unresolved` | rozmowa urwana lub zakończona bez rozwiązania |
| `active` | wątek nadal otwarty, ma ciąg dalszy |
| `superseded` | rozstrzygnięcie wyparte przez późniejszą notatkę; wskaż ją w polu `superseded_by` |
| `evergreen` | wiedza bez daty ważności, nie starzeje się |

Liczone z ostatniego bloku rozmowy, nie z całości.

---

## Oś 5: `signal` (1 do 5, wyliczany)

Nie jest osądem modelu, tylko wynikiem triage z metryk pliku i klasyfikacji. Steruje tym, co awansuje dalej.

Mapowanie na poziomy S z architektury 5.1: **S0=1, S1=2, S2=3 lub 4, S3=5.** We frontmatterze zapisuj wyłącznie liczbę.

| Wartość | Kryterium | Skutek |
|---|---|---|
| 1 | jedna tura użytkownika, brak kodu, `kind: reference-lookup` | brak notatki, tylko wpis w manifeście, plik pozostaje przeszukiwalny |
| 2 | krótka, ale jest kod albo konkretne rozstrzygnięcie | notatka minimalna: summary, tagi, link do źródła |
| 3 | rozmowa robocza, wiele tur, jeden temat | pełna notatka |
| 4 | debugowanie lub budowanie z rozstrzygnięciami | pełna notatka, zasila wiki |
| 5 | długa rozmowa projektowa, decyzje o skutkach | pełna notatka lub kilka, obowiązkowy udział w kompilacji wiki |

---

## Pole `sensitive` (bool)

Ustawiane automatycznie dla domen `zdrowie` i `finanse-podatki` oraz dla każdej notatki zawierającej dane osobowe osób trzecich, dane medyczne, dokumenty lub poświadczenia.

Skutki: notatka trafia do `10-notes/sensitive/`, jest wykluczona z kompilacji wiki, a cały ten podfolder jest wyłączony z gita. Żadna nowa notatka nie zasila automatycznej agregacji profilu; historyczne wyniki pozostają bez zmian. Pole `signal` (wartość treści 1-5) nadal obowiązuje i nie oznacza sygnałów o użytkowniku.

---

## Dwa rodzaje pól, dwa różne standardy

Rozróżnienie dopisane 2026-09-01, po tym jak `entities` rozjechało się do 1338 wartości z 44 grupami wariantów.

**Pola filtrowane** (`domains`, `kind`, `projects`, `status`): agent i człowiek po nich filtrują, więc ich cała wartość polega na porównywalności. Muszą mieć **zamknięty słownik i twardą walidację enumem**. Te przeszły migrację 491 notatek bez jednego naruszenia.

**Pola surowcowe** (`entities`, `summary`, sekcje treści): są wejściem do kroku, który i tak musi je przetworzyć. Mogą być swobodne, ale **krok konsumujący odpowiada za normalizację i odsianie szumu**. `compile.py` robi to przy budowie stron: scala warianty po formie znormalizowanej i odrzuca encje występujące w ponad 20% notatek jako tło środowiskowe.

Błąd, którego to rozróżnienie ma zapobiec: użycia pola surowcowego wprost, tak jakby było klasyfikacją. Nowa oś w taksonomii musi najpierw zostać przypisana do jednej z tych dwóch kategorii.

## Czego ta taksonomia świadomie nie ma

- **Tagu na model źródłowy.** To metadana (`source.model`), nie tag. Pytanie "co wiem o Flyway" nie zależy od tego, który czatbot to powiedział.
- **Tagu `nauka` lub `learning` jako domeny.** Materiał do nauki dostaje domenę swojej dziedziny plus `kind: learning`. Decyzja podtrzymana z poprzedniej wersji vaulta.
- **Tagów oceniających** typu `wazne`, `ciekawe`, `do-przeczytania`. To jest rola osi `signal` i `status`.
- **Hierarchii tagów.** Płasko. Hierarchia kusi, a potem trzeba rozstrzygać, czy `linux/config/pacman` to nadal `linux`.

---
