# Redmine přehled

Lokální webový přehled otevřených úkolů přihlášeného uživatele a projektu `helpdesk`. Synchronizace pravidelně načítá Redmine REST API; první načtení vytvoří výchozí stav, další zachytí nové a změněné otevřené položky. Orientační označení hardwaru používá slova v předmětu a popisu a není zárukou správnosti.

## Spuštění

Vyžaduje Python 3 a povolené REST API. Nastavte `REDMINE_API_KEY` v chráněné konfiguraci prostředí a spusťte `python redmine.py`. Web naslouchá pouze na `127.0.0.1:4091`; pro vzdálený přístup použijte SSH tunel nebo řádně zabezpečenou integraci. Nepublikujte samotnou službu do sítě: nemá přihlášení. Proměnné: `REDMINE_URL`, `REDMINE_DB`, `SYNC_SECONDS`, `PORT`, `OLLAMA_MODEL`. Databáze obsahuje pracovní údaje, chraňte ji a její zálohy.

Volitelné AI shrnutí používá výhradně Ollama na `127.0.0.1:11434` a model určený `OLLAMA_MODEL`. Ollama ani model nejsou součástí aplikace. Bez nich je tlačítko neaktivní. Do modelu se posílá předmět a popis, nikoliv historie či přílohy. Model může chybovat.

Testy: `python -m unittest -v`. Živá integrace potřebuje API klíč. Historie událostí zahrnuje pouze úkoly stále otevřené v aktuálním přehledu. Rychlé odpovědi a e-maily nejsou součástí této verze.

## Mapa zákazníků

Stránka `/mapa` načítá místní soubor `data/customers.json` nebo cestu z `CUSTOMERS_FILE`. Soubor vytvořte pomocí `python import_customers.py seznam.xlsx data/customers.json`; import potřebuje `openpyxl`. Zákaznická data a souřadnice nepatří do Git repozitáře. Poloha se ukládá do lokální SQLite databáze. Číslo z tabulky je odkaz na záznam Redmine, jehož význam se musí ověřit. Tlačítko pro související úkoly prochází aktuálně synchronizované otevřené úkoly a zobrazuje pouze přímé vztahy a rodičovské vazby dostupné přes Redmine API; nelze z toho usuzovat na úplnost všech zákaznických požadavků.

Mapový podklad používá Mapy.com REST API. V chráněné konfiguraci služby nastavte `MAPY_API_KEY` (klíč s povolenou službou mapových dlaždic). Dlaždice požaduje server, který klíč nezpřístupňuje prohlížeči. Mapy.com při požadavku získávají oblast zobrazené mapy; jednotlivé adresy se neposílají. Bez klíče lze používat seznam a ukládat souřadnice, podklad chybí. Pro návrhy souřadnic lze lokálně použít `geocode_ruian.py` s měsíčním ZIPem adresních míst ČÚZK a knihovnou `pyproj`. Jednoznačné shody ulice či části obce, čísla a PSČ jsou pouze kandidáti k ručnímu ověření; nepotvrzují správnou provozovnu. Bez shody zůstává poloha nevyplněná. Souřadnice potvrzené v aplikaci mají přednost před kandidátem. RÚIAN © ČÚZK, CC BY 4.0. Vykreslování a licenční podmínky Mapy.com je před produkčním použitím nutné ověřit s vlastním klíčem.

Příklad: `python geocode_ruian.py data/customers.json /cesta/OB_ADR_csv.zip data/customers-geocoded.json`. Výsledný soukromý soubor lze použít jako `CUSTOMERS_FILE`. Datum zdroje musí odpovídat skutečně použitému ZIPu.

Porovnání zákazníků načítá projekt `zakaznici`, tracker Zákazník a všechny stavy. Přidání vytvoří pouze místní záznam, Redmine se nemění. U zákazníka lze zobrazit jeho adresu a GPS z Redmine. Google vyhledávání se otevře až na výslovný klik a odešle název nebo hledaný text Googlu. Tlačítko kontroly souvisejících úkolů prověřuje přímé vazby a přímé podúkoly dostupné účtu; červená znamená alespoň jeden otevřený, zelená všechny nalezené uzavřené, šedá žádná vazba nebo neúplný stav. Nezahrnuje nepřímé vazby ani údaje skryté oprávněními. Stav je snímek z času kontroly. Automatická kontrola běží po hodině (lze změnit pomocí CUSTOMER_SCAN_SECONDS, minimum 900 sekund), po chybě opakuje po 15 minutách; ruční kontrola zůstává k dispozici.
