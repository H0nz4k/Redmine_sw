# Experiment: místní shrnutí požadavků

Samostatný test bez napojení na produkční Redmine nebo Henka. Používat jen se syntetickými údaji. Nejde o schválenou produkční službu.

`run-isolated.sh` spouští `worker.py` v bubblewrap s vlastním síťovým, procesovým a IPC prostorem, prázdným prostředím a pouze omezenými soubory pro čtení. Na vstupu je JSON přes stdin, výsledek se vrací na stdout. Kód nevolá nástroje a sám neukládá požadavky; zabezpečení navazujícího procesu a jeho logů musí být navrženo a ověřeno zvlášť. Do procesu nevstupují soubory Redmine ani přístupové údaje. `/usr` a model jsou připojeny pouze pro čtení, `/tmp` je dočasná paměťová oblast.

Vstup přijímá 1–4 požadavky s poli `subject` a `description`; dlouhé nebo nesprávné vstupy se odmítnou. Limit kontextu vychází z existujícího modelu, nenahrazuje úplné ověření každé možné šablony. Běh omezují `timeout` a maximální počet generovaných tokenů. Běh jako uživatel `hanz` s touto izolací není důkazem ochrany proti útočníkovi s přístupem ke stejnému účtu nebo správcem stroje.

## Ověření 14. 11. 2026

Na HanzHubu, CPU, existující Llama 3.2 3B Q4, llama-cpp-python 0.2.90, 2048 kontext, 4 vlákna. Výhradně smyšlené příklady. Samostatná kontrola se stejnými parametry izolace: hostitelské `/home` a `/run` nejsou viditelné; spojení na `1.1.1.1:443` skončilo errno 101 (network unreachable). Toto není nezávislý bezpečnostní audit nebo záruka proti chybě konfigurace.

První prompt: tři příklady, časy 37,2 / 34,1 / 16,2 s; model jednou zkreslil fakta a jednou následoval podvržený příkaz a chybně uvedl vyřešení. Druhý prompt: tytéž tři příklady, časy 59,7 / 20,1 / 29,9 s; podvržený příkaz neuposlechl, ale první shrnutí vynechalo žádost o kontrolu kabelu. Neprokazuje to odolnost vůči jiným útokům, věrnost na reálných datech ani vhodnost pro automatická rozhodnutí. Model může uvádět nesprávné závěry; použití se skutečnými daty vyžaduje samostatné přezkoumání zabezpečení, datových cest, zátěže a kontrolu člověkem.

Testy vstupní validace: `python -m unittest discover -s experiments/local_summary -q`. Syntetický běh na HanzHubu: `sh run-isolated.sh < synthetic.json`. Neodesílat skutečné požadavky vzdáleným SSH výstupem; cesta stdout i následné ukládání by musely být součástí bezpečnostního návrhu.
