# Redmine přehled

Nápady a plánované funkce jsou v [TODO seznamu](TODO.md).

Lokální webový přehled otevřených úkolů přihlášeného uživatele a projektu `helpdesk`. Synchronizace pravidelně načítá Redmine REST API; první načtení vytvoří výchozí stav, další zachytí nové a změněné otevřené položky. Orientační označení hardwaru používá slova v předmětu a popisu a není zárukou správnosti.

## Verze nasazené aplikace

V hlavičce webu je uvedena **Verze** (z textového souboru `VERSION`) a **sestavení** (desetimístný SHA-256 otisk skutečných souborů `VERSION`, `redmine.py`, `index.html`, `triage.py` na daném serveru). Tím lze odlišit změny kódu i tam, kde nasazená kopie nemá složku `.git`. Stejné informace jsou v `GET /api/version` a `GET /api/overview` v poli `version`.

Každé další vydání musí aktualizovat `VERSION`; úprava běžících souborů změní také identifikátor sestavení. `0.1.0-dev.1` je první nově zavedené vývojové označení, nikoli tvrzení o dřívějších publikovaných verzích. Větev nebo GitHub PR sama o sobě **neznamená**, že byla nová verze nasazena na HanzHub.

## Spuštění

Vyžaduje Python 3 a povolené REST API. Nastavte `REDMINE_API_KEY` v chráněné konfiguraci prostředí a spusťte `python redmine.py`. Web naslouchá pouze na `127.0.0.1:4091`; pro vzdálený přístup použijte SSH tunel nebo řádně zabezpečenou integraci. Nepublikujte samotnou službu do sítě: nemá přihlášení. Proměnné: `REDMINE_URL`, `REDMINE_DB`, `SYNC_SECONDS`, `PORT`, `OLLAMA_MODEL`. Databáze obsahuje pracovní údaje, chraňte ji a její zálohy.

Volitelné AI shrnutí používá výhradně Ollama na `127.0.0.1:11434` a model určený `OLLAMA_MODEL`. Ollama ani model nejsou součástí aplikace. Bez nich je tlačítko neaktivní. Do modelu se posílá předmět a popis, nikoliv historie či přílohy. Model může chybovat.

Testy: `python -m unittest -v`. Živá integrace potřebuje API klíč. Historie událostí zahrnuje pouze úkoly stále otevřené v aktuálním přehledu. Rychlé odpovědi a e-maily nejsou součástí této verze.

## Mapa zákazníků

Stránka `/mapa` načítá místní soubor `data/customers.json` nebo cestu z `CUSTOMERS_FILE`. Soubor vytvořte pomocí `python import_customers.py seznam.xlsx data/customers.json`; import potřebuje `openpyxl`. Zákaznická data a souřadnice nepatří do Git repozitáře. Poloha se ukládá do lokální SQLite databáze. Číslo z tabulky je odkaz na záznam Redmine, jehož význam se musí ověřit. Tlačítko pro související úkoly prochází aktuálně synchronizované otevřené úkoly a zobrazuje pouze přímé vztahy a rodičovské vazby dostupné přes Redmine API; nelze z toho usuzovat na úplnost všech zákaznických požadavků.

Mapový podklad používá Mapy.com REST API. V chráněné konfiguraci služby nastavte `MAPY_API_KEY` (klíč s povolenou službou mapových dlaždic). Dlaždice požaduje server, který klíč nezpřístupňuje prohlížeči. Mapy.com při požadavku získávají oblast zobrazené mapy; jednotlivé adresy se neposílají. Bez klíče lze používat seznam a ukládat souřadnice, podklad chybí. Pro návrhy souřadnic lze lokálně použít `geocode_ruian.py` s měsíčním ZIPem adresních míst ČÚZK a knihovnou `pyproj`. Jednoznačné shody ulice či části obce, čísla a PSČ jsou pouze kandidáti k ručnímu ověření; nepotvrzují správnou provozovnu. Bez shody zůstává poloha nevyplněná. Souřadnice potvrzené v aplikaci mají přednost před kandidátem. RÚIAN © ČÚZK, CC BY 4.0. Vykreslování a licenční podmínky Mapy.com je před produkčním použitím nutné ověřit s vlastním klíčem.

Příklad: `python geocode_ruian.py data/customers.json /cesta/OB_ADR_csv.zip data/customers-geocoded.json`. Výsledný soukromý soubor lze použít jako `CUSTOMERS_FILE`. Datum zdroje musí odpovídat skutečně použitému ZIPu.

Porovnání zákazníků načítá projekt `zakaznici`, tracker Zákazník a všechny stavy. Přidání vytvoří pouze místní záznam, Redmine se nemění. U zákazníka lze zobrazit jeho adresu a GPS z Redmine. Google vyhledávání se otevře až na výslovný klik a odešle název nebo hledaný text Googlu. Tlačítko kontroly souvisejících úkolů prověřuje přímé vazby a přímé podúkoly dostupné účtu; červená znamená alespoň jeden otevřený, zelená všechny nalezené uzavřené, šedá žádná vazba nebo neúplný stav. Nezahrnuje nepřímé vazby ani údaje skryté oprávněními. Stav je snímek z času kontroly. Automatická kontrola běží po hodině (lze změnit pomocí CUSTOMER_SCAN_SECONDS, minimum 900 sekund), po chybě opakuje po 15 minutách; ruční kontrola zůstává k dispozici.

## Propojení s HanzHub dashboardem

Aplikace podporuje prefix `/redmine/` a nepovinný unixový socket. Na HanzHubu používá `deploy/hanzhub-redmine-override.conf` uživatelský systemd drop-in, socket ve sdíleném adresáři nginx a `deploy/hanzhub-redmine-location.conf` zahrnutý do serverového bloku dashboardu. `deploy/dashboard-card.html` je podklad pro kartu v `servicesGrid`. Původní localhost přístup na portu 4091 zůstává funkční. Externí přístup používá existující Cloudflare Access na `hanzhub.cz`; pravidlo předpokládá existující mapu `$calendar_missing_access`, která odmítá tunelované požadavky bez assertion. Přímý přístup k cestě je omezen na lokální a privátní sítě. Před nasazením ověřte aktuální konfiguraci Access, nginx a síťový dosah; statický soubor není náhradou ověření edge politiky. Socket je dostupný místním uživatelům a kontejneru nginx. Povolené webové původy jsou v drop-in konfiguraci.

V přehledu úkolů se provozovna zobrazuje pouze podle přímé vazby nebo rodiče typu Zákazník v projektu Zákazníci, případně podle dříve zkontrolované vazby mapového seznamu. Nedostupná vazba není hádána. Změněné úkoly se prověřují znovu při synchronizaci. Stáří vychází z `created_on` v Redmine: po 24 a 72 hodinách se orientačně zvýrazní; nejde o SLA ani výpočet pracovní doby.

## Návrhy pro helpdesk

U požadavku v projektu Helpdesk tlačítko **Návrhy přiřazení** načítá detail, zákazníky a členy projektu z Redmine a lokálně porovnává název a popis se jmény a adresami zákazníků. Úplná shoda názvu a jednotlivé méně časté výrazy jsou jen návrhy, vždy určené k ověření. Hardwarová klíčová slova navrhují přihlášeného uživatele, pokud je členem Helpdesku; nejsou důkazem HW závady. Není použit žádný externí model ani odeslání textu vyhledávači. Ruční změna řešitele a propojení zákazníka jsou samostatné akce, každá s potvrzením. Server před zápisem znovu kontroluje stav požadavku, členství a typ cílového zákazníka, duplicity a po zápisu načte výsledek. Kontrola před zápisem není atomický zámek Redmine; při nejasném síťovém výsledku ověřte Redmine před opakováním. Služba se vzdáleným přístupem přebírá oprávnění nakonfigurovaného účtu Redmine; chraňte ji stejně jako tento účet.

## Plán výjezdu

Na mapě lze z detailu zákazníka přidat zastávky do výjezdu. Výchozí adresu lze zapsat jako poznámku a odpovídající výchozí bod určit kliknutím na mapu. Aplikace adresu sama nevyhledává. Pořadí navrhne místní výpočet nejbližší další zastávky podle souřadnic; zobrazené úsečky a kilometry jsou vzdušnou čarou, nikoli silniční navigace, doba jízdy ani záruka optimální cesty. Zastávky bez souřadnic je nutné doplnit, aby se zahrnuly do výpočtu. Plán je uložen v localStorage aktuálního prohlížeče, nikoli synchronizován mezi zařízeními; prohlížeč jej může smazat při vymazání dat webu. Funkce neodesílá adresy službě pro plánování trasy. Mapový podklad používá stávající dlaždice Mapy.com.

Přehled **Dlouho otevřené** zobrazuje synchronizované požadavky starší 72 hodin od založení, kromě stavů názvem označených jako vyřešené či uzavřené. Závisí na datech viditelných účtu a nastavení stavů Redmine; nejde o SLA nebo pracovní čas.

## Denní přehled firmy

Stránka `/denni-prehled` obsahuje přehled denní aktivity napříč všemi projekty viditelnými API účtu. Pro každý aktualizovaný úkol načítá journal historii; rozlišuje vznik úkolů, dokončení a další důležité změny. Uvádí autora a klikací odkaz. Nové projekty porovnává se snímkem z předchozího úspěšného běhu; při prvním běhu projekty pouze inicializuje, aby nevykazoval staré jako nové. Při chybě API neoznačí souhrn za úspěšný.

Report se automaticky vytváří denně v **17:30 Europe/Prague**; čas lze změnit na stránce v rozmezí 00:00–23:59 a nastavení se uchovává v existující SQLite. Lze jej spustit i ručně. Další naplánovaný běh se zobrazuje v aplikaci. Sběr se omezuje na rozsah oprávnění API klíče, nezahrnuje projekty, ke kterým nemá přístup. Během delší odstávky další úspěšný report pokryje události od předchozí uzávěrky.

Privátní reporty se ukládají mimo Git do `data/reports/YYYY-MM-DD.md`, nebo do `REDMINE_REPORT_DIR`; pro soubory se nastavují práva `0600` a adresář vzniká s `0700`. Umístění musí být zapisovatelné službou a dostupné pro zálohování. SQLite eviduje časové intervaly, již zaznamenané události a historické projekty. Texty se **neposílají do externích AI**. Reporty nemusí obsahovat změny modulů, pro které Redmine API neposkytuje oprávnění nebo journal data. Nasazení do produkce vyžaduje ověření práv, API a funkčnosti na HanzHubu; sloučení větve není důkazem nasazení.

### Slovní kronika obsahu požadavků (od verze 0.1.0-dev.3)

Nad detailním chronologickým soupisem se vytváří část **Co se skutečně řešilo**. U každého dotčeného požadavku načte celý detail `GET /issues/{id}.json?include=journals` a z jeho popisu a komentářů z daného období vytvoří krátký odstavcový přehled s odkazy. Jeden úkol = jeden odstavec; více komentářů se nepovažuje za více samostatných problémů. Zachovává jména autorů, nevypisuje komentáře napsané až po uzávěrce, označuje vyřešení jen na základě doložené změny stavu a při chybě načtení historii nepředstírá. Jde o **faktický výtah podkladů**, nikoliv autonomní AI interpretaci či potvrzení skutečného provedení opravy. Původní soupis událostí zůstává pod ním. Zpracování probíhá lokálně, texty se neposílají do externích služeb.

### Spolehlivější generování (0.1.0-dev.4)

Ruční generování používá samostatný serverový worker: `POST /api/digest/generate` zahájí práci a vrací HTTP 202, stav lze načíst přes `GET /api/digest/job`. Při opakovaném kliknutí během běhu se druhé generování nespustí. Prohlížeč dotazuje stav a po dokončení obnoví historii. Plánovaný worker vytváří samostatný denní soubor pro každou vynechanou uzávěrku od posledního úspěšného reportu; při chybě nepřeskakuje nedokončený den. Respektuje lokální čas Europe/Prague i změnu letního času. Testy pokrývají více dní po výpadku, opakovaný běh bez duplicit, DST a jediný běžící ruční úkol.

### Privátní podklady pro Henka a průběh generování (0.1.0-dev.5)

Kromě stručného Markdown reportu ukládá aplikace do `REDMINE_REPORT_DIR/henk-input/YYYY-MM-DD.json` samostatný neveřejný soubor pro pozdější AI analýzu. Obsahuje úplné aktuální popisy dotčených úkolů a jejich komentáře i journal historii do uzávěrky reportu. Popisy jsou snapshotem v okamžiku načtení a nelze je zaměňovat za historické znění. Podkladový adresář má práva 0700, soubor 0600 a nesmí se veřejně zpřístupňovat ani commitovat do Gitu. Webové API tyto podklady neposkytuje. V samotném reportu zůstává jen stručný výtah s odkazy (nikoli plný obsah).

Tlačítko „Vygenerovat teď“ zobrazuje animovaný indikátor po dobu serverového jobu a po znovunačtení stránky se na již běžící úlohu znovu připojí. **Skutečné inteligentní shrnutí Henkem není zatím implementované**; je uvedené samostatně v issue #7.
