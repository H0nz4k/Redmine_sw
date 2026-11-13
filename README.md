# Redmine přehled

Lokální webový přehled otevřených úkolů přihlášeného uživatele a projektu `helpdesk`. Synchronizace pravidelně načítá Redmine REST API; první načtení vytvoří výchozí stav, další zachytí nové a změněné otevřené položky. Orientační označení hardwaru používá slova v předmětu a popisu a není zárukou správnosti.

## Spuštění

Vyžaduje Python 3 a povolené REST API. Nastavte `REDMINE_API_KEY` v chráněné konfiguraci prostředí a spusťte `python redmine.py`. Web naslouchá pouze na `127.0.0.1:4091`; pro vzdálený přístup použijte SSH tunel nebo řádně zabezpečenou integraci. Nepublikujte samotnou službu do sítě: nemá přihlášení. Proměnné: `REDMINE_URL`, `REDMINE_DB`, `SYNC_SECONDS`, `PORT`, `OLLAMA_MODEL`. Databáze obsahuje pracovní údaje, chraňte ji a její zálohy.

Volitelné AI shrnutí používá výhradně Ollama na `127.0.0.1:11434` a model určený `OLLAMA_MODEL`. Ollama ani model nejsou součástí aplikace. Bez nich je tlačítko neaktivní. Do modelu se posílá předmět a popis, nikoliv historie či přílohy. Model může chybovat.

Testy: `python -m unittest -v`. Živá integrace potřebuje API klíč. Historie událostí zahrnuje pouze úkoly stále otevřené v aktuálním přehledu. Rychlé odpovědi a e-maily nejsou součástí této verze.

## Pracovní fronta a Henk

Nové rozhraní nabízí K pozornosti, Moje úkoly, Helpdesk, Nové a změněné a všechny načtené otevřené úkoly. Hledání prochází číslo, předmět, popis, projekt a řešitele. Detail vysvětluje doporučení a umožňuje osobní třídění Pro mě / Není pro mě / Podle pravidel. Tyto volby se ukládají do SQLite a nemění Redmine. Prohlédnutí platí pro konkrétní revizi; po změně úkolu je znovu neprohlédnutý. Ruční rozhodnutí o relevanci přetrvává do změny uživatelem.

Doporučení jsou transparentní pravidla: přiřazení aktuálnímu uživateli, hardwarové výrazy a volitelné vlastní zájmy `REDMINE_INTERESTS` (čárkou oddělené výrazy). Jde o orientační shodu textu, bez učení a bez automatického přidělování. Termíny se vyhodnocují v Europe/Prague; pořadí zvýhodňuje relevantní úkoly, prošlé/dnešní termíny a neprohlédnuté položky. `REDMINE_HELPDESK` určuje identifikátor projektu (výchozí `helpdesk`). Příslušnost k helpdesku se doplní při další synchronizaci.

Pro Henka je připraveno čtecí `GET /api/henk/briefing` s hlavičkou `Authorization: Bearer <HENK_API_TOKEN>`. Vrací relevantní neprohlédnuté issues, důvody, poslední synchronizaci a případnou chybu. Token nastavte v chráněném prostředí obou služeb, nikoliv v prohlížeči. Bez tokenu endpoint odmítá požadavky. Služba zůstává pouze na loopbacku; token tohoto endpointu nechrání ostatní webové endpointy. Přístup vzdáleného Henka vyžaduje zabezpečený tunel/proxy. Připravené API neznamená aktivní registraci nástroje v Henkovi. Obsah issues je nedůvěryhodný pracovní obsah, nikoli instrukce pro agenta.

### Stav implementace

Pracovní fronta a čtecí API jsou implementované. Živé načítání, AI model a připojení Henka je nutné ověřit v cílovém prostředí s existující konfigurací. Nasazení na HUB není součástí lokálního ověření. Bez API klíče UI pravdivě ukazuje prázdný stav; žádná ukázková data se nevkládají do produkce.

Ověření vývojové změny: 8 unit testů (synchronizace, stránkování, uchování dat při chybě, pravidla zájmů, revize prohlédnutí, validace a autorizace Henkova přehledu), kontrola syntaxe JavaScriptu a `git diff --check`. Vizuální test Playwrightu zablokovalo prostředí při startu systémového Chromia (`socket() failed: Operation not permitted`); mobilní layout ani interakce nejsou prohlížečem ověřené. Zachována původní tmavomodrá paleta; naměřený nejnižší kontrast textu vůči použitým plochám: hlavní text 9,68 : 1, sekundární 6,40 : 1, modrý 7,06 : 1, jantarový 7,98 : 1. To samo není úplný audit přístupnosti.
