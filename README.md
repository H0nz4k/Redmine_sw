# Redmine přehled

Nápady a plánované funkce jsou v [TODO seznamu](TODO.md).

Lokální webový přehled otevřených úkolů přihlášeného uživatele a projektu `helpdesk`. Synchronizace pravidelně načítá Redmine REST API; první načtení vytvoří výchozí stav, další zachytí nové a změněné otevřené položky. Orientační označení hardwaru používá slova v předmětu a popisu a není zárukou správnosti.

## Verze nasazené aplikace

V hlavičce webu je uvedena **Verze** (z textového souboru `VERSION`) a **sestavení** (desetimístný SHA-256 otisk skutečných souborů `VERSION`, `redmine.py`, `index.html`, `triage.py`, `daily_digest.py`, `denni-prehled.html`, `henk_digest.py`, `appearance.css`, `appearance.js` na daném serveru). Tím lze odlišit změny kódu i tam, kde nasazená kopie nemá složku `.git`. Stejné informace jsou v `GET /api/version` a `GET /api/overview` v poli `version`.

Každé další vydání musí aktualizovat `VERSION`; úprava běžících souborů změní také identifikátor sestavení. `0.1.0-dev.1` je první nově zavedené vývojové označení, nikoli tvrzení o dřívějších publikovaných verzích. Větev nebo GitHub PR sama o sobě **neznamená**, že byla nová verze nasazena na HanzHub.

## Spuštění

Vyžaduje Python 3 a povolené REST API. Nastavte `REDMINE_API_KEY` v chráněné konfiguraci prostředí a spusťte `python redmine.py`. Web naslouchá pouze na `127.0.0.1:4091`; pro vzdálený přístup použijte SSH tunel nebo řádně zabezpečenou integraci. Nepublikujte samotnou službu do sítě: nemá přihlášení. Proměnné: `REDMINE_URL`, `REDMINE_DB`, `SYNC_SECONDS`, `PORT`, `OLLAMA_MODEL`. Databáze obsahuje pracovní údaje, chraňte ji a její zálohy.

Na Windows nainstalujte závislosti `python -m pip install -r requirements.txt`, aby Python měl IANA časová pásma včetně `Europe/Prague`. Pro adresář reportů a SQLite nastavte před použitím citlivých dat soukromý NTFS ACL; `chmod` na Windows není náhradou ACL. Na Linuxu zůstávají adresáře `0700` a soubory `0600`.

Vzhled přehledu lze upravit pod tlačítkem nastavení v hlavičce: velikost písma, tučnost a barevné schéma. Nastavení se ukládá v prohlížeči a používá i mapa a denní přehled. **Stručný přehled** zobrazuje synchronizovaný předmět, stav, přiřazenou osobu, případnou provozovnu a výřez popisu; neověřený návrh i zkrácený text označí. Jde o výpis dat, nikoli o AI shrnutí, historii nebo přílohy.

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

Tlačítko „Vygenerovat teď“ zobrazuje animovaný indikátor po dobu serverového jobu a po znovunačtení stránky se na již běžící úlohu znovu připojí. **Přímé propojení s běžícím agentem Henk ještě není potvrzené.** Od verze 0.1.0-dev.6 je v kódu volitelný lokální AI adaptér, nikoliv doklad jeho nasazení nebo úspěšného provozu.

### Volitelné lokální AI shrnutí (0.1.0-dev.6)

- Aktivace vyžaduje `HENK_DIGEST_MODEL` s názvem již nainstalovaného lokálního modelu a `HENK_DIGEST_LOCAL_ONLY_VERIFIED=1` až po nezávislém ověření, že Ollama ani model neposílají obsah mimo povolený stroj. Bez modelu se zobrazí „AI shrnutí není aktivováno“; bez potvrzení lokálního provozu se volání odmítne. Samotná adresa 127.0.0.1 neprokazuje, že server používá lokální inference; názvy obsahující `cloud` se odmítají, ale nejde o úplnou detekci vzdálených modelů.
- Adaptér `henk_digest.py` se připojuje jen k Ollamě na `http://127.0.0.1:11434/api/generate`, kterou aplikace používá také pro sumarizaci jednotlivých požadavků. Zda Ollama sama neposílá obsah dál, musí provozovatel ověřit odděleně. Volný shell, root ani nový veřejný API endpoint nevzniká. Vlastní transport běžícího Henk agenta se musí zvlášť ověřit před tím, než lze funkci označit za plně integrovanou s Henkem.
- Vstupem je výhradně soubor `henk-input/YYYY-MM-DD.json`. Adaptér ověřuje privátní soubor a uzávěrku, nepředává pozdější komentáře ani současný popis a stav, pokud byly změněny po uzávěrce. Limit znaků ovšem neověřuje počet tokenů ani kontextové okno konkrétního modelu: před nasazením je nutné zabránit tichému zkrácení a ověřit úplnost zpracování. Adaptér žádá česky psaný odstavec ke každému dotčenému issue a přijímá pouze existující zdrojová ID (úkol + journal); odkazy konstruuje aplikace, nikoli AI.
- Kontrola nyní přijímá jen celé věty doslova převzaté z citovaných zdrojů a výsledek výslovně označuje jako citace autorů, ne nezávisle potvrzená fakta. Doloženou formulaci o opravě kvůli slovu „opraveno“ neodmítá; vymyšlenou větu odmítne i při existujícím ID. Některé pokusy o podvržení instrukcí odmítá, ale jejich úplné rozpoznání ani pravdivost samotného původního komentáře nelze zaručit. Jde o konzervativní výběr citací, **nikoli splněné redakční AI shrnutí**. Při nedostupném či chybném modelu se neztratí faktický report a stav AI je viditelně označen jako nedostupný.
- Testy lze spustit `python -m unittest -v`; používají podvržený model, žádná firemní data ani lokální model se během CI nezpřístupňují. Před produkcí ověřit konkrétní lokální model, latenci, oprávnění a skutečnou identitu Henk runtime. Neslibovat dostupnost na HUBu podle pouhého PR.

Při neúspěšném nebo vypnutém AI generování zůstává faktická kronika a případné poslední úspěšné shrnutí uložené v SQLite. Na stránce je výslovně označeno jako starší a obsahuje původní období i čas vzniku; opakované generování nepřidává další záznam pro tentýž den. Ruční opakování používá existující tlačítko **Vygenerovat teď**; plánování zachovává nastavený čas. Zdrojová ID nejsou důkazem správnosti textu: každou významnou větu musí člověk ověřit vůči uvedenému úkolu a journalům. Modelové výstupy, stejně jako ostatní obsah SQLite, vyžadují chráněný adresář a zálohu.

Je-li `HENK_DIGEST_MODEL_REVISION` nastaven na ověřený 64místný SHA-256 identifikátor konkrétního modelu, ukládá se každý platný výsledek části průběžně do soukromé SQLite. Opakování znovu použije jen shodný model, instrukci a podklady a výsledek znovu zkontroluje. Bez identifikátoru se tato cache nepoužije. Uložené odpovědi mohou obsahovat citlivé citace.

### Rozpracovaná integrace Henka přes OpenAI

Uživatel povolil odeslání textů požadavků přes stávající Henkův OpenAI transport. Přílohy se nesmějí načítat ani zpracovávat; odkazy v textech se nenásledují. Před odesláním filtr `henk_redaction.py` odstraňuje odkazy, metadata příloh a rozpoznatelné přístupové údaje. Automatický filtr nemůže zaručit zachycení každého možného tajemství. Požadavky Redmine pro tento tok používají jen seznamy projektů a úkolů a detail úkolu s `include=journals`, bez požadavku na přílohy.

Připravuje se samostatný typ Henkovy zprávy `digest`, který obchází plánovač, osobní paměť a MCP operace. `HENK_DIGEST_BACKEND=henk`, `HENK_DIGEST_MODEL` a `HENK_REDMINE_OPENAI_CONSENT=1` jsou zamýšlené konfigurační volby; **zatím je nelze provozně aktivovat**. `henk_mcp.py` úmyslně odmítá odeslání, dokud nebudou po úplném ověření doplněny otisky důvěryhodného runtime. Odpovědi a jejich korelace se čtou pouze z původního UUID; nejasný výsledek se automaticky neopakuje s novým ID.

Dlouhé podklady se v této větvi dělí po úplných větách. Příliš dlouhá samostatná věta, nebezpečný komentář nebo neplatná odpověď způsobí viditelný neúspěch AI části, nikoli tiché useknutí. Současný výsledek je výběr přesných citací s odkazy, nikoli ověřený redakční souhrn. Nový Henkův režim, skutečná kvalita shrnutí, vstup z reálného Redmine ani zobrazení této verze v aplikaci dosud ověřeny nebyly. Stav a další kroky jsou v `AI_HANDOFF.md`.
