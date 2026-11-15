# Kandidát textového API Henka — nasazení a návrat

**Čeká na schválení:** skutečný syntetický test i cílený izolovaný průchod s čerstvými texty Redmine, Henkem a zobrazením v prohlížeči prošly. Produkční služby nebyly změněny. Tento dokument není souhlasem s nasazením.

## Přístup a konfigurace

Klíč OpenAI byl místně dodán v souboru níže a model `gpt-4.1-mini` se skutečně použil v izolovaném syntetickém i snapshotovém testu. Přihlášení Codexu se nepoužívá.

Klíč OpenAI je v `/etc/hanzhub/secrets/redmine-openai-key`, vlastník root, skupina root, režim 0600; nevypisuje se, nepředává do chatu ani neukládá do repozitáře.

Pro samostatný čerstvý test byl uživatelem místně připraven oddělený čtecí API klíč v `/etc/hanzhub/secrets/redmine-api-key`. Je určen jen pro izolovaný test a není součástí nasazovací konfigurace. Případná opětovná příprava v Bash (existující soubor se prázdným souborem nepřepisuje):

```bash
sudo install -d -m 0700 -o root -g root /etc/hanzhub/secrets
sudo test -e /etc/hanzhub/secrets/redmine-api-key || sudo install -m 0600 -o root -g root /dev/null /etc/hanzhub/secrets/redmine-api-key
sudoedit /etc/hanzhub/secrets/redmine-api-key
sudo chown root:root /etc/hanzhub/secrets/redmine-api-key
sudo chmod 0600 /etc/hanzhub/secrets/redmine-api-key
```

Tento Redmine klíč je jen pro izolovaný čtecí test, nikoli změna služby; má zpřístupnit stejné úkoly a projekty jako přehled. Pro nastavení služby je nutný samostatný schválený provozní krok. Automatická kontrola zamítla dřívější pokus převzít klíč z `/proc/<PID>/environ`, proto se tento způsob nepoužívá.

Zamýšlený systemd drop-in `hanzhub-mcp-agent.service`:

```ini
[Service]
LoadCredential=redmine-openai-key:/etc/hanzhub/secrets/redmine-openai-key
Environment=HENK_REDMINE_OPENAI_CONSENT=1
Environment=HENK_SUMMARY_OPENAI_MODEL=gpt-4.1-mini
```

Zamýšlený drop-in uživatelské služby `redmine-assistant.service`:

```ini
[Service]
Environment=HENK_DIGEST_BACKEND=henk
Environment=HENK_DIGEST_MODEL=gpt-4.1-mini
Environment=HENK_REDMINE_OPENAI_CONSENT=1
Environment=HENK_DIGEST_MODEL_REVISION=51effe2169eaf35d545de48f74e622b1be12b7b7fb33331afbf5f74617c9ae4e
```

Revision je otisk implementace API kandidáta; změna modelu i podkladů vstupuje samostatně do klíče cache. Model ve zprávě a v Henkově konfiguraci se musí shodovat. `store: false` vypíná ukládání odpovědi pro pozdější načtení přes Responses API; samo o sobě nepředstavuje záruku nulové retence všech provozních dat OpenAI.

## Konkrétní soubory a předpoklady

Kandidát Henka `ecb7ae5` je patch `henk-openai-candidate.patch`, SHA-256 `320d5460a4fc4bca0c252d37320c97a4743a44627f02fbc1a30c9463f5f2e6cb` pro soubor s LF. Používá nulový kontext; před použitím je povinné ověřit přesný základ a `git apply --check --unidiff-zero` ve **stagingové kopii**, nikoli přímo v `/opt`. Základ zjištěný 15. 11. 2026:

| Cíl v `/opt/hanzhub-project-control/mcp-channel` | Původní SHA-256 | Kandidát SHA-256 |
|---|---|---|
| `agent_worker.py` | `03475797a83cb613ee4d7ae4e7d2e3931a8c676c0cf026b193fcb9214fe8cd68` | `ea21e90994111075ac88cb01e457f3208d8d759b780e12f46168c08b50c30cad` |
| `channel.py` | `2982cb001e717cb7d8fb2e81838a30387c934bd171c8c5616243bfae07839073` | `9207b6effd4174852a1f136f16bbc91750a219b0da28a3b8872096d30765da8a` |
| `henk_openai.py` | neexistuje | `51effe2169eaf35d545de48f74e622b1be12b7b7fb33331afbf5f74617c9ae4e` |
| `henk_redaction.py` | neexistuje | `033f8e177b293be03f0981a8cd37bbf45a99a9e064402979fde2e9fdb55de892` |

Pro aplikaci `/home/hanz/redmine-assistant` kandidát zahrnuje soubory `redmine.py`, `daily_digest.py`, `henk_digest.py`, `henk_mcp.py` a `henk_redaction.py` z přesně schváleného commitu Redmine. Před nasazením zkontrolovat všechny cíle včetně existence a dosavadních otisků; poslední zjištěné otisky `redmine.py` a `daily_digest.py` jsou v `AI_HANDOFF.md`. Nepřepisovat odchylky: nejprve je porovnat a znovu připravit kandidáta. Neměnit databázi, frontu, privátní reporty ani čas plánování.

## Postup k pozdějšímu schválení

1. V odděleném dočasném prostředí připravit staging ze současných dvou původních souborů, aplikovat patch a ověřit výše uvedené čtyři výsledné otisky. Přenést jen syntetické testovací podklady; žádná příloha ani soukromý log.
2. Skutečný syntetický test prošel za 1,35 s. Izolovaná aplikace čerstvě načetla jeden reálný úkol, přes samostatný MCP stdio server a frontu jej předala Henkovi, uložila souhrn a zobrazila jej v Chrome. Při kontrole vyšlo najevo, že produkční HTML používá navíc endpoint výňatků, který původní kandidát postrádal; následná oprava jej zachovává. Stejný uložený výsledek se pak bez opakovaného volání AI ověřil s finálním backendem a současným produkčním HTML včetně výňatků, historie a ovládání. Zdrojové věty se ověřily doslovně; zaznamenané požadavky byly `/issues.json`, `/issues/{id}.json?include=journals` a `/projects.json`, bez příloh a přesměrování. V oddělené kopii uloženého výsledku prošla simulace výpadku a zachování posledního úspěšného shrnutí. Tím nevzniká souhlas s nasazením.
3. Připravit zálohu **přesných** existujících souborů, jejich vlastníků a režimů do nového root-only adresáře mimo webový strom. Oba cílové drop-iny jsou nové a jejich neexistence byla ověřena; ostatní drop-iny se nemění. Zaznamenat všechny neexistující cíle, aby šly při návratu odebrat pouze tyto nově přidané soubory. Tajný soubor se nepřepisuje ani nezálohuje do balíčku.
4. Předložit ke schválení přesné commity, otisky, drop-iny a pořadí zásahů. Po schválení zkontrolovat běhy/frontu a nedopustit, aby byla při výměně nebo návratu zpráva `digest` převzata starou verzí. Zastavit příslušné služby až po dokončení nebo samostatném vyřešení rozpracovaných požadavků. Ověřit baseline znovu; při rozdílu zastavit.
5. Instalovat ověřené čtyři soubory Henka jako root:root 0644 s novým časem změny, nainstalovat schválené soubory Redmine a drop-iny. Před startem workeru zajistit časový odstup alespoň dvě sekundy; klient odmítne proces, který je starší než instalované soubory. Provést potřebný systemd daemon-reload, spustit `hanzhub-mcp.service`, `hanzhub-mcp-agent.service` a uživatelskou `redmine-assistant.service`, ověřit jejich stav a skutečný build. Pak spustit jediný cílený průchod a porovnat výsledek se zdroji.
6. Při návratu opět zajistit, že žádný `digest` nečeká ani neběží; nejasný výsledek nerozesílat znovu. Zastavit dotčené služby, obnovit přesně původní soubory a drop-iny se zachovaným vlastnictvím a režimy, odstranit jen nově přidané cíle zaznamenané při záloze, provést daemon-reload a spustit původní služby. Ověřit původní otisky, stavy a zobrazení posledního úspěšného reportu. Neodstraňovat databázi, uložené reporty ani API klíč.

## Připravený balíček a zkouška návratu

Na HUBu je root-only staging `/var/tmp/hanz-redmine-review-32glm4zl` s kandidátem Redmine z commitu `55385e9`, Henkem z `ecb7ae5`, dvěma navrženými drop-iny a zálohami čtyř původních souborů. SHA-256 přeneseného balíčku je `e9d07b326a02506a5dc974891dc0b2ad4145c206d5d5dca597121cf6e9144d29`; očekávaný build aplikace při nezměněných ostatních souborech je `183ee9f600`. Ověření všech otisků, kompilace kandidátních Python souborů a zkušební obnova záloh v oddělené kopii včetně vlastníků, práv a časů prošly. Porovnání provozních funkcí ani API cest nenašlo odstraněnou funkci. Staging v `/var/tmp` není zárukou přežití rebootu; bezprostředně před nasazením vše znovu ověřit a při změně nebo ztrátě znovu připravit.

Schvalovaný rozsah: nahradit dva Henkovy a dva aplikační zdrojové soubory, přidat dva Henkovy a tři aplikační moduly a oba výše uvedené nové drop-iny; řízeně restartovat `hanzhub-mcp.service`, `hanzhub-mcp-agent.service` a uživatelskou `redmine-assistant.service`. Žádná databáze, historie, report ani tajný soubor se nenahrazují.
