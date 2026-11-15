# Redmine a Henk — stav textového souhrnu

Stav: kandidát **není nasazen**. Větev `feature/henk-digest-continuation` a dosavadní commity zůstaly zachovány. Uživatel schvaluje zpracování textů Redmine přes OpenAI a zakazuje načítání příloh a následování odkazů. Nasazení vyžaduje samostatný souhlas. API klíč OpenAI je již uložen na HUBu jako root-only soubor `/etc/hanzhub/secrets/redmine-openai-key`; jeho hodnotu nevypisovat, nekopírovat do Gitu ani do logů.

## Co bylo skutečně ověřeno

- Kandidát Henka `ecb7ae5` používá přímý Responses API požadavek modelu `gpt-4.1-mini`, `tools: []`, `tool_choice: none` a `store: false`, bez Codexu a smyčky nástrojů. Model vybírá indexy vět; výsledný text a zdrojová ID se sestavují deterministicky. Necitovatelné části jsou označeny a výsledek prochází druhou kontrolou proti zdrojům.
- Skutečný syntetický test finální verze trval 1,35 s. Zahrnul doloženou opravu, otevřený problém, obě strany rozporu a ignoroval podvržený pokyn. Při vývoji se opravilo přeformulování zdroje a spojení titulku bez interpunkce s další citací.
- Izolovaný průchod nad jedním skutečným **již uloženým** privátním snapshotem z Redmine použil skutečný samostatný MCP stdio server, frontu, API model a testovací aplikaci. Ruční spuštění, uložení AI výsledku, kontrola citací a zdrojového odkazu a jejich zobrazení v Chrome prošly. Bezpečné čtení tohoto snapshotu nezahrnovalo stažení příloh. V testu se neprováděl nový požadavek na Redmine, identita produkčního procesu se nahrazovala izolovanou testovací instancí a ověření produkčních otisků bylo proto v testu vypnuté.
- Zdroj běžícího sběru výslovně používá detail úkolu s `include=journals`, bez odkazu na endpoint příloh. Nový klient `digest_request` navíc povoluje jen seznamy úkolů a projektů a jejich textové detaily s historií a odmítá HTTP přesměrování; tato hranice prošla cílenými testy. Skutečné nové síťové načtení ale v tomto průchodu ověřeno nebylo.

## Zbývající přístup a postup

Automatická kontrola zamítla pokus převzít Redmine API klíč z `/proc/<PID>/environ` přes root jako čtení přihlašovacího údaje z nezamýšleného zdroje. Tento způsob se nepoužil. Pro čerstvý cílený test je připraven postup s odděleným čtecím klíčem `/etc/hanzhub/secrets/redmine-api-key` (root:root 0600), který uživatel může vložit místně bez odeslání do chatu. Návod a konkrétní návrat jsou v `henk-runtime/DEPLOYMENT.md`.

Po dodání klíče lze spustit připravený izolovaný průchod `data/run_real_henk_live.py` v tomto workspace (adresář `data/` je lokální a není v Gitu). Používá jen explicitně povolené endpointy, neloguje texty a žádá jen jeden úkol. Ověřit skutečné HTTP cesty bez příloh, zobrazení, návaznost a zachování výsledku. Poté znovu zkontrolovat aktuální baseline, zálohu, přesné otisky a předložit nasazení ke schválení. Při nejasném výsledku zprávu neopakovat s novým UUID.

Henkův kandidátní patch pro čtyři provozní soubory je `henk-runtime/henk-openai-candidate.patch`; starší experimentální patch je zachován, ale nepoužívá se. Oddělená vývojová kopie `data/henk-control-work` se do Gitu neukládá.
