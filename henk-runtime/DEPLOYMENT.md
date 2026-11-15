# Kandidát textového API Henka — nasazení a návrat

**Nenasazovat:** před schválením chybí API klíč, skutečný syntetický běh, porovnání reálných textů a ověření zobrazení. Tento dokument popisuje přesný kandidát; není souhlasem ani důkazem provozní připravenosti.

## Přístup a konfigurace

Na HUBu dosud nebyl zjištěn `OPENAI_API_KEY` v prostředí účtu `hanz`, služby Redmine ani procesu Henka. Neautentizovaný HTTPS dotaz na `https://api.openai.com/v1/models` vrátil HTTP 401 z účtů `hanz` i `codex`. Neověřuje oprávnění účtu, fakturaci ani dostupnost modelu. Dokumentace uvádí podporu Responses a strukturovaného výstupu u `gpt-4.1-mini`; dostupnost pro zamýšlený API projekt je nutno vyzkoušet. Přihlášení Codexu se nepoužívá.

Uživatel nebo správce může samostatně připravit API klíč s přístupem k modelu a potřebným limitem v souboru `/etc/hanzhub/secrets/redmine-openai-key`, vlastník root, skupina root, režim 0600; klíč se nevypisuje, nepředává do chatu ani neukládá do repozitáře. Příklad lokálního vložení na HUBu v Bash (existující soubor se prázdným souborem nepřepisuje):

```bash
sudo install -d -m 0700 -o root -g root /etc/hanzhub/secrets
sudo test -e /etc/hanzhub/secrets/redmine-openai-key || sudo install -m 0600 -o root -g root /dev/null /etc/hanzhub/secrets/redmine-openai-key
sudoedit /etc/hanzhub/secrets/redmine-openai-key
sudo chown root:root /etc/hanzhub/secrets/redmine-openai-key
sudo chmod 0600 /etc/hanzhub/secrets/redmine-openai-key
```

Před načtením souboru službou je nutný nový schválený provozní krok.

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
Environment=HENK_DIGEST_MODEL_REVISION=ab7a9558518751c38c57defec2a238ce8fe774d68522f4f6276a53c1a4e5b18e
```

Revision je otisk implementace API kandidáta; změna modelu i podkladů vstupuje samostatně do klíče cache. Model ve zprávě a v Henkově konfiguraci se musí shodovat. `store: false` vypíná ukládání odpovědi pro pozdější načtení přes Responses API; samo o sobě nepředstavuje záruku nulové retence všech provozních dat OpenAI.

## Konkrétní soubory a předpoklady

Kandidát Henka `c4975cf` je patch `henk-openai-candidate.patch`, SHA-256 `e8f2fb17378eae52e2107f31554e56f1e26621b95420afa74f53a3b9c26711e0` pro soubor s LF. Používá nulový kontext; před použitím je povinné ověřit přesný základ a `git apply --check --unidiff-zero` ve **stagingové kopii**, nikoli přímo v `/opt`. Základ zjištěný 15. 11. 2026:

| Cíl v `/opt/hanzhub-project-control/mcp-channel` | Původní SHA-256 | Kandidát SHA-256 |
|---|---|---|
| `agent_worker.py` | `03475797a83cb613ee4d7ae4e7d2e3931a8c676c0cf026b193fcb9214fe8cd68` | `ea21e90994111075ac88cb01e457f3208d8d759b780e12f46168c08b50c30cad` |
| `channel.py` | `2982cb001e717cb7d8fb2e81838a30387c934bd171c8c5616243bfae07839073` | `9207b6effd4174852a1f136f16bbc91750a219b0da28a3b8872096d30765da8a` |
| `henk_openai.py` | neexistuje | `ab7a9558518751c38c57defec2a238ce8fe774d68522f4f6276a53c1a4e5b18e` |
| `henk_redaction.py` | neexistuje | `033f8e177b293be03f0981a8cd37bbf45a99a9e064402979fde2e9fdb55de892` |

Pro aplikaci `/home/hanz/redmine-assistant` kandidát zahrnuje soubory `redmine.py`, `daily_digest.py`, `henk_digest.py`, `henk_mcp.py` a `henk_redaction.py` z přesně schváleného commitu Redmine. Před nasazením zkontrolovat všechny cíle včetně existence a dosavadních otisků; poslední zjištěné otisky `redmine.py` a `daily_digest.py` jsou v `AI_HANDOFF.md`. Nepřepisovat odchylky: nejprve je porovnat a znovu připravit kandidáta. Neměnit databázi, frontu, privátní reporty ani čas plánování.

## Postup k pozdějšímu schválení

1. V odděleném dočasném prostředí připravit staging ze současných dvou původních souborů, aplikovat patch a ověřit výše uvedené čtyři výsledné otisky. Přenést jen syntetické testovací podklady; žádná příloha ani soukromý log.
2. Ověřit API klíč a model nejprve skutečným syntetickým testem v izolované instanci Henkovy schopnosti. Následně v oprávněném izolovaném prostředí ověřit skutečné texty, cestu načítání bez příloh a odkazy a výsledek v aplikaci. Tím ještě nevzniká souhlas s nasazením.
3. Připravit zálohu **přesných** existujících souborů, jejich vlastníků a režimů a obou původních drop-inů do nového root-only adresáře mimo webový strom. Zaznamenat neexistující soubory, aby šly při návratu odebrat pouze tyto nově přidané soubory. Tajný soubor se nepřepisuje ani nezálohuje do balíčku.
4. Předložit ke schválení přesné commity, otisky, drop-iny a pořadí zásahů. Po schválení zkontrolovat běhy/frontu a nedopustit, aby byla při výměně nebo návratu zpráva `digest` převzata starou verzí. Zastavit příslušné služby až po dokončení nebo samostatném vyřešení rozpracovaných požadavků. Ověřit baseline znovu; při rozdílu zastavit.
5. Instalovat ověřené čtyři soubory Henka jako root:root 0644 s novým časem změny, nainstalovat schválené soubory Redmine a drop-iny. Před startem workeru zajistit časový odstup alespoň dvě sekundy; klient odmítne proces, který je starší než instalované soubory. Provést potřebný systemd daemon-reload, spustit `hanzhub-mcp.service`, `hanzhub-mcp-agent.service` a uživatelskou `redmine-assistant.service`, ověřit jejich stav a skutečný build. Pak spustit jediný cílený průchod a porovnat výsledek se zdroji.
6. Při návratu opět zajistit, že žádný `digest` nečeká ani neběží; nejasný výsledek nerozesílat znovu. Zastavit dotčené služby, obnovit přesně původní soubory a drop-iny se zachovaným vlastnictvím a režimy, odstranit jen nově přidané cíle zaznamenané při záloze, provést daemon-reload a spustit původní služby. Ověřit původní otisky, stavy a zobrazení posledního úspěšného reportu. Neodstraňovat databázi, uložené reporty ani API klíč.
