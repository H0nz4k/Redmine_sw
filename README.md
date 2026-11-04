# Redmine přehled

Lokální webový přehled otevřených úkolů přihlášeného uživatele a projektu `helpdesk`. Synchronizace pravidelně načítá Redmine REST API; první načtení vytvoří výchozí stav, další zachytí nové a změněné otevřené položky. Orientační označení hardwaru používá slova v předmětu a popisu a není zárukou správnosti.

## Spuštění

Vyžaduje Python 3 a povolené REST API. Nastavte `REDMINE_API_KEY` v chráněné konfiguraci prostředí a spusťte `python redmine.py`. Web naslouchá pouze na `127.0.0.1:4091`; pro vzdálený přístup použijte SSH tunel nebo řádně zabezpečenou integraci. Nepublikujte samotnou službu do sítě: nemá přihlášení. Proměnné: `REDMINE_URL`, `REDMINE_DB`, `SYNC_SECONDS`, `PORT`, `OLLAMA_MODEL`. Databáze obsahuje pracovní údaje, chraňte ji a její zálohy.

Volitelné AI shrnutí používá výhradně Ollama na `127.0.0.1:11434` a model určený `OLLAMA_MODEL`. Ollama ani model nejsou součástí aplikace. Bez nich je tlačítko neaktivní. Do modelu se posílá předmět a popis, nikoliv historie či přílohy. Model může chybovat.

Testy: `python -m unittest -v`. Živá integrace potřebuje API klíč. Historie událostí zahrnuje pouze úkoly stále otevřené v aktuálním přehledu. Rychlé odpovědi a e-maily nejsou součástí této verze.
