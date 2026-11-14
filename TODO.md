# Co má Redmine přehled umět

Tento seznam slouží k zapisování a prioritizaci nápadů pro aplikaci. Nové položky přidávej jako nezaškrtnuté; za hotové je označ až po ověření v běžící aplikaci. Neobsahuje zákaznická data ani přístupové údaje.

## Skutečný stav a návaznost — 14. 11. 2026

- HanzHub: běží přehled s nastavením vzhledu, stručným přehledem v dialogu, mapou a základním denním přehledem. Vzhled a dialog byly ověřeny v prohlížeči se synchronizovanými daty.
- Novější denní kronika `0.1.0-dev.5` byla nasazena 14. 11. 2026; plán 17:30, existující report a soukromá cesta byly ověřeny, databáze i reporty zálohovány. Skutečné API odmítá zlomky sekund ve filtru (HTTP 422). Oprava filtru prošla izolovaným testem nad kopií databáze se skutečným API (0 událostí), 38 testy a kontrolou oprávnění. Byla nasazena 14. 11. 2026; služba po restartu běží a kontrola potvrdila nezměněné reporty i jejich záznamy. Další plánovaná uzávěrka v 17:30 nebyla ještě ověřena.
- Místní AI shrnutí zůstává experiment: síťově izolovaný model byl vyzkoušen pouze na syntetických datech, prokazatelně chyboval v prvním pokusu a jeho použití pro skutečné požadavky není schváleno.
- Popisek filtru a stručného přehledu „Přiřazeno“ byl nasazen na HanzHubu 14. 11. 2026 a ověřen v prohlížeči. Po restartu nové kroniky se identifikátor sestavení znovu vypočetl.

## Rozpracované a navazující úkoly

### Plánování servisních výjezdů

- [ ] Převést ručně zadanou výchozí adresu na souřadnice pomocí místních adresních dat; navrženou polohu umožnit ověřit.
- [ ] Připravit místní výpočet trasy po silnicích, včetně odhadu délky a času jízdy, bez odesílání adres externí službě.
- [ ] Umožnit zohlednit otevřené požadavky zákazníků při výběru zastávek.
- [ ] Prozkoumat možnosti úprav pořadí zastávek, návratu do výchozího místa a ukládání více plánů napříč zařízeními.

Současná verze nabízí výběr zastávek a orientační seřazení podle vzdálenosti vzdušnou čarou; adresa odjezdu je poznámka, bod se vybírá na mapě. Plán se ukládá v konkrétním prohlížeči.

### Automatické třídění Helpdesku (issue #1)

- [ ] Přiřazovat jednoznačné nepřiřazené HW závady bezpečným workerem (nejprve dry-run, pak explicitní aktivace).
- [ ] Ukládat trvalé návrhy, schválení/odmítnutí, přečteno/nepřečteno a audit.
- [ ] Přidat upozornění na nové relevantní úkoly, rychlý detail a potvrzení přímo v aplikaci.
- [ ] Ověřit pravidla na skutečných tiketech před zapnutím automatického zápisu.

První implementační větev `feature/helpdesk-triage`: lokální konzervativní klasifikace, vysvětlení důvodu, přehled „HW návrhy“ a jednotkové testy. **Automatické zápisy do Redmine zatím vypnuté.** Detail zadání: https://github.com/H0nz4k/Redmine_sw/issues/1

### Denní firemní kronika Redminu — issue #3

- [ ] Každý den ve výchozím čase 17:30 Europe/Prague (nastavitelném přímo v aplikaci) sestavit souvislou zprávu o událostech ve všech dostupných projektech a od všech dostupných autorů.
- [ ] V nastavení aplikace umožnit změnit čas reportu (HH:MM), trvale uložit volbu a ukazovat další plánované spuštění; změna nesmí způsobit duplicity nebo ztrátu dat.
- [ ] Vycházet z Redmine API a historie změn: co vzniklo, co kdo dokončil nebo uzavřel a jaké zásadní změny proběhly.
- [ ] Nad soupisem zobrazovat slovní kroniku z popisů bugů a komentářů, s uvedením autorů a odkazy. První implementace ve větvi feature/digest-narrative, produkčně ověřit.
- [ ] U každé důležité události uvést člověka, projekt a klikací odkaz na původní záznam.
- [ ] Zprávu automaticky ukládat v aplikaci včetně historie a ručního spuštění, bez duplicit a bez ztrát při výpadku.
- [ ] Napojit Henka na privátní denní podklady pro skutečné AI shrnutí problémů a řešení, viz [issue #7](https://github.com/H0nz4k/Redmine_sw/issues/7). Dnes se jen ukládají vstupy, Henk dosud souhrny netvoří.
- [ ] Později zvážit upozornění a možnost přečtení zprávy Henkem nahlas.

**Nejde o filtr mých úkolů ani Helpdesku:** cílem je přehled o dění v celé firmě. Podrobné zadání: https://github.com/H0nz4k/Redmine_sw/issues/3

### Helpdesk a úkoly

- [ ] Zlepšovat návrhy provozovny podle ověřitelných údajů ve zprávě a kontaktech zákazníků; vysvětlovat použité indicie.
- [ ] Prověřit dostupnost údajů o odesílateli z helpdesk pluginu přes podporované API.
- [ ] Rozšířit návrhy řešitele podle obsahu požadavku a ověřených pravidel; změny v Redmine provádět až po potvrzení.
- [ ] Rozšířit sledování dlouho otevřených požadavků podle skutečných stavů Redmine; případně nastavit hranice a pracovní dobu.
- [ ] Připravit rychlou odpověď na požadavek s náhledem a potvrzením před odesláním.
- [ ] Připravit e-mailová upozornění na nové a relevantní požadavky.

### Lokální AI

- [ ] Zabezpečit a ověřit lokální AI shrnutí před použitím s reálnými údaji; experiment na syntetických datech trval 20–60 s a první varianta následovala podvržený pokyn.
- [ ] Prověřit lokální AI návrhy kategorie, provozovny a řešitele; zachovat kontrolu člověkem a vysvětlení.

### Přístup a zařízení

- [ ] Vyřešit chybu načítání dat přes veřejnou adresu a ověřit přihlášený přístup přes Cloudflare Access.
- [ ] Ověřit přehled a mapu na mobilu a zlepšit ovládání pro výjezdy.
- [ ] Prozkoumat pozdější mobilní aplikaci nebo instalovatelnou webovou aplikaci.

## Základ, který aplikace již obsahuje

- [x] Synchronizovaný přehled mých úkolů a požadavků helpdesku.
- [x] Nastavení vzhledu, záložková ikona a stručný přehled požadavku v dialogu.
- [x] Odkaz na mapu v Redmine a ikona na kartě Redmine na hlavním dashboardu.
- [x] Návrhy provozovny a řešitele s potvrzením před změnou v Redmine.
- [x] Mapa zákazníků s přímými vazbami a stavem souvisejících úkolů.
- [x] Orientační stáří požadavků a první přehled dlouho otevřených položek.
- [x] První lokální plán výjezdu podle přímé vzdálenosti.
