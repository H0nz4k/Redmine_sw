# Hlas Henka: kandidát, nikoli nasazená služba

Základ hlasového kódu je ReSpeaker `fde55d8d80b2f7844afb56a3be34868414aa7479`. Soubory `wake_word.py`, `voice_bridge.py`, `led_status.py` a `helpdesk_voice_adapter.py` v tomto adresáři jsou kandidát pro `/home/hanz/ReSpeaker/src/`; `redmine.py` v kořeni je kandidát pro `/home/hanz/redmine-assistant/redmine.py`. Hlasový adaptér dotazuje jen lokální soukromý socket Redmine a ostatní věty předává existujícímu `henk_local_adapter.py`. Socket přijímá pouze vlastní UID, data získává přímo ze seznamu Redmine se všemi stavy; přílohy ani detaily úkolů nenačítá. Odpověď do Fish obsahuje redigované předměty nejvýše pěti požadavků a počet zbývajících. Omezení ASR a neshoda otázky vyžadují skutečný hlasový test; obecné otázky vyžadují funkční existující inbox.

## Navrhovaný rozsah po samostatném schválení

1. Zkontrolovat stav fronty Henk, aktivní Redmine a runtime pinů; běžící nebo nejasné úlohy neopakovat. Ověřit stejné baseline SHA-256 níže, `git status` ReSpeakeru a neexistenci nových souborů. Při odchylce zastavit a znovu připravit.
2. Vytvořit privátní zálohu čtyř nahrazovaných souborů se zachováním práv a vlastnictví, drop-inů a současných stavů služeb. Nikdy nepřepisovat databázi, souhrny, tajné klíče ani Henkovu frontu.
3. Instalovat kandidátní `redmine.py`, čtyři hlasové soubory a uživatelskou jednotku `respeaker-voice.service`; vlastníci `hanz`, režimy 0644. Přidat uživatelský drop-in pro `redmine-assistant.service` s `Environment=REDMINE_VOICE_SOCKET=/run/user/1000/redmine-voice.sock`.
4. Provést user daemon-reload, restart pouze `redmine-assistant.service` a ověřit jeho AI souhrn, historii a stav. Spustit již nainstalovanou systémovou službu `respeaker-henk-inbox.service`, která je nyní enabled, ale inactive. Aktivovat a spustit novou uživatelskou hlasovou službu. Henkův worker, jeho runtime a existující plán souhrnů neměnit.
5. S uživatelem ověřit mikrofon, správnou aktuální odpověď, mluvený zvuk a časy. Kandidát nastaví při naslouchání zelenou LED přes dříve fyzicky ověřené SPI0; před nasazením ověřit piny i sdílení sběrnice znovu.

Návrat: zastavit a zakázat novou hlasovou jednotku, obnovit čtyři zálohované soubory a původní konfiguraci Redmine; odstranit pouze nové cíle, jejichž neexistence byla zaznamenána před instalací; user daemon-reload a restart Redmine. Systémový inbox vrátit do původního inactive stavu, jeho existující enablement zachovat. Zkontrolovat službu Redmine, build, historii a stav Henkovy fronty. Databázi ani uložené výsledky neobnovovat ze snapshotu.

## Baseline z 15. 11. 2026

- `redmine.py`: `bf2b27a6d876751ce29120cbe47b5d9379edf6d55baa6f3f4b62b32e39b95436`
- `wake_word.py`: `94dd5ed0d3eac7c4d5a6d6d924003f3f48c12cd239e269915f81d92c4524d8fb`
- `voice_bridge.py`: `ec6e3369a5246c8f403d0fdb1b172b0e4636ea46d1d492ab83ed2cbea8d94312`
- `led_status.py`: `7f60a8894047d79fc2e18b0ed486e1d0b466d7af20469104e408b8126378f46e`
- `henk_local_adapter.py` beze změny: `b0954597466fa8007c8ac9b48fe96f6a4cdd5e95ebe4fc59d79da4f3574d5e90`

Před nasazením doplnit skutečný, chráněný staging se zálohami a ověřit návrat. Aktuální kandidát nesmí být označen za provozně ověřený, dokud neprojde řečená otázka s čerstvými daty.
