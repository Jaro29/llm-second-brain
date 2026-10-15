---
id: n-0000
title: Tytuł notatki
summary: >
  Jedno do trzech zdań PISANYCH POD RETRIEVAL: problem, rozwiązanie, pułapka.
  Nie "Rozmowa dotyczy X", tylko co konkretnie z niej wynika.

source:
  model: claude            # claude | chatgpt | perplexity | gemini | ai-studio | ai-mode
  file: 00-archive/claude/0000_....md
  conversation_id: ""
  segment: 1/1
  date: 2026-01-01         # data ROZMOWY, nie przetworzenia
  lang: pl

domains: []                # 1-3, wyłącznie z taxonomy.md
kind: reference-lookup     # dokładnie 1, z taxonomy.md
projects: []               # 0-3
status: resolved           # resolved | unresolved | active | superseded | evergreen
signal: 1                  # 1-5
sensitive: false

entities: []
question: ""
outcome: ""
has_code: false
code_langs: []

related: []                # po ID: [n-0203]
superseded_by: null        # n-XXXX, jeśli status = superseded
wiki: []

ingest_version: "1.3"
confidence: 0.0
content_hash: ""
human_reviewed: false      # ---- poniżej tej linii pipeline nie pisze ----
human_notes: ""
human_tags: []
---

# Tytuł notatki

## Kontekst
Dwa do czterech zdań: skąd wziął się problem, jaki był stan wyjściowy.

## Pytanie
Dokładnie to, co miało zostać ustalone. Jedno zdanie.

## Rozwiązanie
Sedno. To jest sekcja, którą agent wciągnie do odpowiedzi.

## Kod
Bloki kodu w całości, z językiem. Nigdy skracane.

## Pułapki i uwagi
Co nie zadziałało i dlaczego. Najwyższa wartość na wiersz w całym vaulcie.

## Decyzje
Tylko jeśli zapadły. Format: decyzja / alternatywy / uzasadnienie / data.

## Źródło
Plik w `00-archive/` plus zakres tur, np. tury 34 do 71.
