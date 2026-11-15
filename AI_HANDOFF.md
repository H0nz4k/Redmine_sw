# Redmine a Henk — pokračování textového souhrnu

Stav k 15. 11. 2026: **kandidát implementován a ověřen s podvrženou odpovědí; skutečný model, reálné podklady ani nasazení nejsou ověřeny**. Výchozí větev `feature/henk-digest-continuation` a commity včetně `0b48271` zůstaly zachovány. Uživatel schválil zpracování textových podkladů přes OpenAI, nesouhlasil s obcházením schvalování nasazení. Přílohy se nesmějí načítat, analyzovat ani posílat; odkazy z textů se nenásledují. Tajné údaje nesmějí do chatu, Gitu ani veřejných logů.

## Co je připraveno

- Henkův kandidát `c4975cf` v oddělené lokální kopii `data/henk-control-work` obsahuje samostatnou schopnost pro typ zprávy `digest`: přímý Responses API požadavek s prázdným seznamem nástrojů, bez Codexu a bez smyčky nástrojů. Příslušný patch pro čtyři provozní soubory je `henk-runtime/henk-openai-candidate.patch`; kopie `data/` se do Gitu neukládá. Předchozí experimentální patch zůstává zachován, nepoužívá se.
- Klient Redmine zachovává UUID, kontroluje korelaci a otisky kandidáta i start běžícího workeru. Výsledek ověřuje jako celé doslovné citace s existujícími zdroji. Výpadek zachová faktický report a poslední úspěšný AI výsledek. Hodnota `HENK_DIGEST_MODEL` musí odpovídat Henkovu `HENK_SUMMARY_OPENAI_MODEL`.
- Denní sběr používá jen explicitně povolené endpointy `/issues.json`, `/issues/{id}.json?include=journals` a `/projects.json`; odmítá přesměrování. Zpracování nevyžádá přílohy. Redakce omezuje zjevné přístupové údaje, odkazy a metadata příloh, ale žádný automatický filtr nemůže zaručit zachycení všech tajných údajů.
- Na Windows prošlo 49 cílených testů, dva byly přeskočeny kvůli právům/symlinkům. Na HUBu prošlo stejných 49 bez přeskočení a dalších pět syntetických testů Henkova adaptéru. HTTP odpověď modelu byla podvržená; obsahovou kvalitu skutečného modelu testy nedokládají.

## Konkrétní překážka

V prostředí běžící služby Redmine, účtu `hanz` ani běžící služby Henka nebyl nalezen `OPENAI_API_KEY`. Z účtů `hanz` a `codex` odpovědělo oficiální OpenAI API na neautentizovaný dotaz HTTP 401. API tedy není ověřeno s účtem ani modelem. `gpt-4.1-mini` má podle oficiální dokumentace podporu Responses a strukturovaného výstupu, jeho dostupnost pro konkrétní projekt je neznámá. Přihlašovací údaje Codexu se nepoužívají.

Klíč lze předat **místně**, nikoli v chatu, jako root-only soubor `/etc/hanzhub/secrets/redmine-openai-key` s režimem 0600. Použití tohoto souboru a změna služby vyžadují schválený provozní krok; přesné kandidátní drop-iny, otisky, předpoklady a návrat jsou v `henk-runtime/DEPLOYMENT.md`.

## Pokračování

1. Po zajištění podporovaného API přístupu v izolovaném prostředí spustit skutečný syntetický příklad: doložená oprava, otevřený problém, protichůdné komentáře a škodlivá instrukce. Změřit čas a porovnat význam každého tvrzení se zdroji, nejen ověřit JSON.
2. Teprve potom provést autorizovaný průchod s reálnými texty, záznamem jen cest/parametrů požadavků dokázat nenačítání příloh a porovnat zobrazený souhrn s původními zdroji. Žádné reálné texty v tomto pokračování nebyly modelu odeslány.
3. Znovu zkontrolovat provozní baseline, vytvořit konkrétní obnovitelnou zálohu a po ověření předložit přesné nasazení ke schválení. Při nejasném stavu fronty neposílat zprávy s novým UUID.
