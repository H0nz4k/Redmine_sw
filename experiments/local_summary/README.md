# Experiment: místní shrnutí požadavků

Samostatný test bez napojení na produkční Redmine nebo Henka. Používat jen se syntetickými údaji. Nejde o schválenou produkční službu.

`run-isolated.sh` spouští `worker.py` v bubblewrap s vlastním síťovým, procesovým a IPC prostorem, prázdným prostředím a pouze omezenými soubory pro čtení. Na vstupu je JSON přes stdin, výsledek se vrací na stdout. Kód nevolá nástroje a sám neukládá požadavky; zabezpečení navazujícího procesu a jeho logů musí být navrženo a ověřeno zvlášť. Do procesu nevstupují soubory Redmine ani přístupové údaje. `/usr` a model jsou připojeny pouze pro čtení, `/tmp` je dočasná paměťová oblast.

Vstup přijímá 1–4 požadavky s poli `subject` a `description`; dlouhé nebo nesprávné vstupy se odmítnou. Limit kontextu vychází z existujícího modelu, nenahrazuje úplné ověření každé možné šablony. Běh omezují `timeout` a maximální počet generovaných tokenů. Běh jako uživatel `hanz` s touto izolací není důkazem ochrany proti útočníkovi s přístupem ke stejnému účtu nebo správcem stroje.

## Ověření 14. 11. 2026

Na HanzHubu, CPU, existující Llama 3.2 3B Q4, llama-cpp-python 0.2.90, 2048 kontext, 4 vlákna. Výhradně smyšlené příklady. Samostatná kontrola se stejnými parametry izolace: hostitelské `/home` a `/run` nejsou viditelné; spojení na `1.1.1.1:443` skončilo errno 101 (network unreachable). Toto není nezávislý bezpečnostní audit nebo záruka proti chybě konfigurace.

První prompt: tři příklady, časy 37,2 / 34,1 / 16,2 s; model jednou zkreslil fakta a jednou následoval podvržený příkaz a chybně uvedl vyřešení. Druhý prompt: tytéž tři příklady, časy 59,7 / 20,1 / 29,9 s; podvržený příkaz neuposlechl, ale první shrnutí vynechalo žádost o kontrolu kabelu. Neprokazuje to odolnost vůči jiným útokům, věrnost na reálných datech ani vhodnost pro automatická rozhodnutí. Model může uvádět nesprávné závěry; použití se skutečnými daty vyžaduje samostatné přezkoumání zabezpečení, datových cest, zátěže a kontrolu člověkem.

Testy vstupní validace: `python -m unittest discover -s experiments/local_summary -q`. Syntetický běh na HanzHubu: `sh run-isolated.sh < synthetic.json`. Neodesílat skutečné požadavky vzdáleným SSH výstupem; cesta stdout i následné ukládání by musely být součástí bezpečnostního návrhu.

## Syntetická kronika a skutečný runtime — 15. 11. 2026

`digest_synthetic.py` obsahuje pevně zadané smyšlené časové osy; nepřijímá vstupní soubor ani pracovní data. Samostatně spuštěná kopie existujícího modelu na HUBu použila instrukci z Redmine PR #9, dva krátké příklady, CPU, `n_ctx=2048`, 4 vlákna a síťově izolovaný bubblewrap. První příklad (411 znaků JSON, 339 tokenů včetně instrukce bez chatové šablony) skončil za 76,5 s a vrátil jen předmět „Testovací e-mail neodchází“ a existující ID. Druhý (440 znaků, 357 tokenů) skončil za 46,0 s a vrátil jen předmět „Smyšlený terminál nečte čipy“ a ID. Nedoplnil podvržené tvrzení o opravě, ale ani u jednoho příkladu nepopsal zjištění a další postup. **Akceptace shrnutí neprošla.** Jde o dva syntetické příklady, ne o důkaz obecné odolnosti nebo výkonu na skutečných datech; limit tokenů zde není přesným měřením chatové šablony.

Ověření skutečného hosta: `hanz-agent.service` provozuje llama.cpp na `192.168.1.3:8087`; `/health` vrátil 200, `/v1/models` 404, na `127.0.0.1:11434` Ollama nenaslouchala. Čtený `/opt/hanz-agent/agent_server.py` má `/chat`, který může podle odpovědi modelu volat shellové nástroje; není tedy bezpečnou beznástrojovou cestou pro nedůvěryhodné podklady. Henkův samostatný `hanzhub-mcp-agent.service` běží pod účtem `codex`; zdroj nasazeného modelového workeru nastavuje `model_provider="openai"`. Cesta `data/reports/henk-input` patří účtu `hanz` a její předkové mají režim 0700. Tyto poznatky nezaručují pozdější konfiguraci ani opravňují předat pracovní obsah externímu modelu.

Před další realizací je nutné navrhnout skutečně lokální beznástrojový transport s úzce omezeným přístupem ke vstupům, ověřit model na syntetických datech i na souhlasem vymezených lokálních podkladech a každé tvrzení zkontrolovat proti zdroji. Přístupová práva, aktivace a nasazení vyžadují samostatný schválený provozní postup. Stávající faktický report musí zůstat dostupný při selhání AI. Žádné nasazení, změna práv ani skutečné pracovní vstupy nebyly při tomto testu provedeny.
