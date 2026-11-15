# Redmine a Henk — kandidát čeká na souhlas s nasazením

Větev `feature/henk-digest-continuation` zachovává všechny dosavadní commity. Produkční služby nebyly změněny. Uživatel schvaluje zpracování textů Redmine přes OpenAI, zakazuje načítání příloh a následování odkazů a výslovně požaduje samostatný souhlas s nasazením. Klíče se nesmějí vypisovat, kopírovat do Gitu ani logovat.

## Ověřený kandidát

- Aplikační kód `55385e9`, Henkův kandidát `ecb7ae5`. Přímý Responses API požadavek modelu `gpt-4.1-mini` nemá nástroje ani vykonávací smyčku. Model vybírá indexy vět; text a zdrojová ID se sestaví deterministicky, necitovatelné části jsou viditelně označeny. Klient chrání UUID, korelaci, otisky a načtení správného workeru.
- Skutečný syntetický test trval 1,35 s a obstál pro doloženou opravu, otevřený problém, protichůdné komentáře i podvrženou instrukci. Cílené testy finální verze: 67 ve Windows, z toho dva přeskočené; 53 na HUBu a sedm testů Henkova adaptéru bez přeskočení.
- Po místním dodání samostatného čtecího Redmine klíče prošel čerstvý izolovaný průchod Redmine → MCP stdio → Henk → OpenAI → uložení → aplikace. Záznam cesty obsahoval pouze `/issues.json`, `/issues/{id}.json?include=journals` a `/projects.json`; přílohy se nenačítaly. Kontrola citací vůči zdrojům a zobrazení reportu, historie a odkazu v Chrome prošly. Produkční HTML používá navíc endpoint výňatků; zjištěnou chybějící funkci oprava `55385e9` zachovala a stejný uložený výsledek se poté bez nového volání AI ověřil s finálním backendem a produkčním HTML, včetně výňatků, historie a ovládání. Produkční HTML se nepřepisuje. Test zpracoval jediný úkol; izolovaná instance nahrazovala produkční worker a kontrolu jeho otisků.
- V oddělené kopii tohoto výsledku simulovaný výpadek prokázal zachování AI záznamu i zobrazení posledního úspěchu jako staršího. Žádná produkční databáze nebo report se při testu neměnily.

## Připravené nasazení a návrat

Přesné soubory, konfigurace, postup a omezení jsou v `henk-runtime/DEPLOYMENT.md`. Na HUBu je chráněný staging `/var/tmp/hanz-redmine-review-32glm4zl`: balíček SHA-256 `e9d07b326a02506a5dc974891dc0b2ad4145c206d5d5dca597121cf6e9144d29`, očekávaný aplikační build `183ee9f600`, zálohy původních čtyř souborů a konzistentní online SQLite snapshot produkční databáze. Ověření všech otisků, kompilace a zkouška obnovy v oddělené kopii prošly. Před samotným nasazením znovu ověřit baseline, neexistenci nových cílů, stav fronty i služeb; staging `/var/tmp` nemusí přežít restart.

Schvalovaný zásah zahrnuje čtyři soubory Henka, pět souborů aplikace, dva nové systemd drop-iny a řízený restart tří uvedených služeb. Nový provoz přidá tabulky pro AI výsledky a požadavky. Návrat obnoví čtyři původní soubory, odstraní jen nově přidané soubory a drop-iny a restartuje původní služby; databázi, přidané tabulky, historii, reporty ani tajné soubory nepřepisuje. Obnova databázového snapshotu by mohla ztratit novější data a vyžaduje samostatný souhlas. Nejasný výsledek fronty se neopakuje s novým UUID. Po schválení nasadit pouze tento kandidát, při odchylce zastavit a po startu ověřit skutečný build, účet/credential, reálný tok i zobrazení.

Automatická kontrola v předchozím kroku odmítla převzetí Redmine klíče z `/proc/<PID>/environ`; tento způsob nebyl použit. Uživatel následně místně poskytl oddělený root-only čtecí klíč, který byl použit pro čerstvý izolovaný test. Tento čtecí klíč není součástí produkční konfigurace nasazení.
