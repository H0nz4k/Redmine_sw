# Hlas Henka: kandidát, nikoli nasazená služba

**Stav 15. 11. 2026:** schválený kandidát `8f5965a` byl nasazen a po opakovaných nechtěných aktivacích a uživatelem potvrzené nesprávné hlasové odpovědi vrácen. Obnovení souborů, Redmine, historie a původního stavu služeb prošlo; podrobnosti jsou v `AI_HANDOFF.md`. Opětovné nasazení stejného kandidáta se nedoporučuje. Následná malá změna kandidáta mění pouze barvu stavu zpracování ze žluté na fialovou, což uživatel fyzicky potvrdil; dosud není nasazena. Skutečná návaznost běžné konverzace potřebuje novější podporu vlákna v inboxu a samostatné ověření.

Základ hlasového kódu je ReSpeaker `fde55d8d80b2f7844afb56a3be34868414aa7479`. Soubory `wake_word.py`, `voice_bridge.py`, `led_status.py` a `helpdesk_voice_adapter.py` v tomto adresáři jsou kandidát pro `/home/hanz/ReSpeaker/src/`; `redmine.py` v kořeni je kandidát pro `/home/hanz/redmine-assistant/redmine.py`. Hlasový adaptér dotazuje jen lokální soukromý socket Redmine a ostatní věty předává existujícímu `henk_local_adapter.py`. Socket přijímá pouze vlastní UID, data získává přímo ze seznamu Redmine se všemi stavy; přílohy ani detaily úkolů nenačítá. Odpověď do Fish obsahuje redigované předměty nejvýše pěti požadavků a počet zbývajících. Omezení ASR a neshoda otázky vyžadují skutečný hlasový test; obecné otázky vyžadují funkční existující inbox.

## Navrhovaný rozsah po samostatném schválení

1. Zkontrolovat stav fronty Henk, aktivní Redmine a runtime pinů; běžící nebo nejasné úlohy neopakovat. Ověřit stejné baseline SHA-256 níže, `git status` ReSpeakeru a neexistenci nových souborů. Při odchylce zastavit a znovu připravit.
2. Vytvořit privátní zálohu čtyř nahrazovaných souborů se zachováním práv a vlastnictví, drop-inů a současných stavů služeb. Nikdy nepřepisovat databázi, souhrny, tajné klíče ani Henkovu frontu.
3. Instalovat kandidátní `redmine.py`, čtyři hlasové soubory a uživatelskou jednotku `respeaker-voice.service`; vlastníci `hanz`, režimy 0644. Instalovat `redmine-voice.conf` jako `~/.config/systemd/user/redmine-assistant.service.d/60-voice.conf`.
4. Provést user daemon-reload, restart pouze `redmine-assistant.service` a ověřit jeho AI souhrn, historii a stav. Spustit již nainstalovanou systémovou službu `respeaker-henk-inbox.service`, která je nyní enabled, ale inactive. Aktivovat a spustit novou uživatelskou hlasovou službu. Henkův worker, jeho runtime a existující plán souhrnů neměnit.
5. S uživatelem ověřit mikrofon, správnou aktuální odpověď, mluvený zvuk a časy. Kandidát nastaví při naslouchání zelenou LED přes dříve fyzicky ověřené SPI0; před nasazením ověřit piny i sdílení sběrnice znovu.

Návrat: zastavit a zakázat novou hlasovou jednotku, obnovit čtyři zálohované soubory a původní konfiguraci Redmine; odstranit pouze nové cíle, jejichž neexistence byla zaznamenána před instalací; user daemon-reload a restart Redmine. Systémový inbox vrátit do původního inactive stavu, jeho existující enablement zachovat. Zkontrolovat službu Redmine, build, historii a stav Henkovy fronty. Databázi ani uložené výsledky neobnovovat ze snapshotu.

## Baseline z 15. 11. 2026

- `redmine.py`: `bf2b27a6d876751ce29120cbe47b5d9379edf6d55baa6f3f4b62b32e39b95436`
- `wake_word.py`: `94dd5ed0d3eac7c4d5a6d6d924003f3f48c12cd239e269915f81d92c4524d8fb`
- `voice_bridge.py`: `ec6e3369a5246c8f403d0fdb1b172b0e4636ea46d1d492ab83ed2cbea8d94312`
- `led_status.py`: `7f60a8894047d79fc2e18b0ed486e1d0b466d7af20469104e408b8126378f46e`
- `henk_local_adapter.py` beze změny: `b0954597466fa8007c8ac9b48fe96f6a4cdd5e95ebe4fc59d79da4f3574d5e90`

Izolovaná hlasová zkouška na HUBu 15. 11. prošla: čerstvý Redmine v danou chvíli vracel nula dnešních požadavků a uživatel potvrdil, že stejnou odpověď slyšel. Měřený čas od posledního vzorku hlasu k prvnímu PCM předanému přehrávači byl 4,26 s; nejde o akustické měření. Uživatel rovněž potvrdil fyzické zelené LED a výstup T60. Fish `/v1/asr` má `language=cs`, které je podle [dokumentace Fish](https://docs.fish.audio/features/speech-to-text) jen vodítkem. Zjištěné výrazné nízkofrekvenční rušení se v kandidátovi filtruje digitálně před detekcí a přepisem. Rozpoznání jedné věty neprokazuje spolehlivost probouzení ani obecné konverzace; provozní inbox je neaktivní a běžná konverzace přes něj zatím nebyla znovu vyzkoušena.

Chráněný staging `/var/tmp/henk-voice-review-4Nr8Fr1T` obsahuje kandidáta a zálohy čtyř původních souborů; porovnání záloh s baseline a obnova v izolované kopii prošly. Staging nemusí přežít restart: před případným schváleným nasazením znovu ověřit obsah, otisky, konfiguraci, stav fronty a služeb.
