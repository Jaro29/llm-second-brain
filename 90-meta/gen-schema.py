#!/usr/bin/env python3
"""Generuje schema-notatki.json z taxonomy.md. Enumy nie moga sie rozjechac,
bo sa czytane ze slownika, nie przepisywane recznie. Uruchom po kazdej zmianie taksonomii."""
import json, re, pathlib
tax = (pathlib.Path(__file__).parent.parent / 'taxonomy.md').read_text(encoding='utf-8')
sec = lambda h: tax.split('## '+h)[1].split('\n## ')[0]
domains = re.findall(r'^### ([a-z0-9-]+)$', sec('Oś 1'), re.M)
kinds   = re.findall(r'^\| `([a-z-]+)` \|', sec('Oś 2'), re.M)
projs   = re.findall(r'^\| `([a-z-]+)` \|', sec('Oś 3'), re.M)
stats   = re.findall(r'^\| `([a-z]+)` \|', sec('Oś 4'), re.M)
assert len(domains) > 15 and kinds and projs and stats, (len(domains), kinds, projs, stats)
S = {"type":"object","additionalProperties":False,
 "required":["title","summary","domains","kind","projects","status","signal","sensitive",
             "entities","question","outcome","has_code","code_langs","segment_of","turns",
             "kontekst","rozwiazanie","kod","pulapki","decyzje"],
 "properties":{
  "title":{"type":"string","maxLength":90},
  "summary":{"type":"string","minLength":80,"maxLength":700},
  "domains":{"type":"array","minItems":1,"maxItems":3,"uniqueItems":True,"items":{"enum":domains}},
  "kind":{"enum":kinds},
  "projects":{"type":"array","maxItems":3,"uniqueItems":True,"items":{"enum":projs}},
  "status":{"enum":stats},
  "signal":{"type":"integer","minimum":1,"maximum":5},
  "sensitive":{"type":"boolean"},
  "entities":{"type":"array","maxItems":12,"uniqueItems":True,"items":{"type":"string"}},
  "question":{"type":"string"},
  "outcome":{"type":"string"},
  "has_code":{"type":"boolean"},
  "code_langs":{"type":"array","uniqueItems":True,"items":{"type":"string"}},
  "segment_of":{"type":"string","description":"np. 2/3; 1/1 gdy rozmowa jednotematyczna"},
  "turns":{"type":"string","description":"zakres tur uzytkownika, np. 4-13"},
  "kontekst":{"type":"string"},
  "rozwiazanie":{"type":"string"},
  "kod":{"type":"string","description":"bloki kodu w calosci lub pusty string"},
  "pulapki":{"type":"string","description":"co nie zadzialalo i dlaczego; pusty string gdy brak"},
  "decyzje":{"type":"string"},
  "superseded_by":{"type":"string","description":"n-XXXX albo pusty string"},
  "confidence":{"type":"number","minimum":0,"maximum":1}}}
S["required"] = list(S["properties"].keys())   # strict: kazde pole obowiazkowe
pathlib.Path(__file__).with_name('schema-notatki.json').write_text(json.dumps(S,ensure_ascii=False,indent=1),encoding='utf-8')
print(f"schema-notatki.json: {len(domains)} domen, {len(kinds)} kind, {len(projs)} projektow, {len(stats)} statusow")
