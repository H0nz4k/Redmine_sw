#!/usr/bin/env python3
"""Push-to-talk bridge: ReSpeaker -> Fish STT -> HENK adapter -> Fish TTS -> Creative T60.

The adapter is an explicit executable that reads ONE JSON request from stdin and
returns ONE JSON reply on stdout. No arbitrary HTTP endpoints or shell execution
are inferred from recognized speech. No action is executed without configured
HENK adapter and the normal HENK approval flow.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import uuid
import urllib.error
import urllib.request

ASR_URL = "https://api.fish.audio/v1/asr"
TTS_URL = "https://api.fish.audio/v1/tts"
CARD = "plughw:CARD=seeed2micvoicec,DEV=0"
SPEAKER = "plughw:CARD=T60,DEV=0"
DEFAULT_VOICE = "c70c6c20aee74d8c98b01dab6743e02e"
VOICE_RE = re.compile(r"^[a-fA-F0-9]{32}$")


def key():
    value = os.environ.get("FISH_API_KEY")
    if not value:
        path = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "respeaker/fish-api-key"
        if path.exists():
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError("Fish API klíč musí být běžný soubor s oprávněním 0600.")
            value = path.read_text(encoding="utf-8").strip()
    if not value:
        value = getpass.getpass("Fish Audio API klíč: ")
    if not value:
        raise ValueError("Chybí FISH_API_KEY")
    return value


def load_voice():
    source = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "respeaker/fish-voice-id"
    value = os.environ.get("FISH_VOICE_ID") or (source.read_text(encoding="utf-8").strip() if source.is_file() else DEFAULT_VOICE)
    if not VOICE_RE.fullmatch(value):
        raise ValueError("Neplatné Fish voice ID")
    return value


def call(command, *, input_text=None, timeout=60):
    p = subprocess.run(command, input=input_text, text=input_text is not None, check=True,
                       capture_output=True, timeout=timeout)
    return p.stdout


ASR_SPEAKER_MARKER = re.compile(r"<\|speaker:\d+\|>")
ASR_AUDIO_CUE = re.compile(r"\[[^\]\r\n]{1,65}\]")


def clean_transcript(text):
    """Remove only Fish metadata, not guessed words or grammar errors."""
    if not isinstance(text, str):
        raise ValueError("Fish ASR nevrátil text")
    value = ASR_SPEAKER_MARKER.sub(" ", text)
    value = ASR_AUDIO_CUE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        raise ValueError("Fish ASR nevrátilo použitelnou řeč")
    return value


def transcribe(wav, api_key):
    """Fish REST STT, Czech hint and plain-text output (no diarization cues)."""
    boundary = "henk-" + uuid.uuid4().hex
    data = wav.read_bytes()
    fields = (("language", "cs"), ("diarize", "false"),
              ("tag_audio_events", "false"), ("ignore_timestamps", "true"))
    chunks = []
    for name, value in fields:
        chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n"
                       f"\r\n{value}\r\n").encode("ascii"))
    chunks.extend([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"question.wav\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n".encode("ascii"),
        data, f"\r\n--{boundary}--\r\n".encode("ascii"),
    ])
    model = os.environ.get("FISH_ASR_MODEL", "transcribe-1-pro")
    if model not in ("transcribe-1", "transcribe-1-pro"):
        raise ValueError("Nepodporovaný Fish ASR model")
    req = urllib.request.Request(ASR_URL, data=b"".join(chunks), method="POST",
        headers={"Authorization": f"Bearer {api_key}", "model": model,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        payload = json.load(resp)
    if not isinstance(payload, dict):
        raise ValueError("Fish ASR nevrátilo JSON objekt")
    return validate_czech_transcript(payload)


# Fish `language=cs` is a language HINT, not a hard lock. Auto-detection
# can still choose e.g. Bengali on noisy audio. NEVER forward such text to
# HENK, particularly because its intent might trigger a broker request.
NON_CZECH_SCRIPT = re.compile(
    r"[\u0980-\u09ff\u0900-\u097f\u0b80-\u0bff\u0c00-\u0c7f"
    r"\u0c80-\u0cff\u0d00-\u0d7f\u0e00-\u0e7f\u3040-\u30ff"
    r"\u3400-\u9fff\uac00-\ud7af\u0600-\u06ff]"
)


def validate_czech_transcript(payload):
    """Accept plausible Czech ASR only; never guess or translate user intent."""
    language = payload.get("language_code")
    if language is not None and language not in ("cs", "sk"):
        raise ValueError("Fish ASR rozeznalo jiný jazyk než češtinu")
    text = clean_transcript(payload.get("text", ""))
    if NON_CZECH_SCRIPT.search(text):
        raise ValueError("Fish ASR vrátilo text v jiném písmu než čeština")
    return text


def synthesize(text, destination, api_key, voice):
    payload = json.dumps({"text": text, "reference_id": voice, "format": "mp3"},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(TTS_URL, data=payload, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "model": "s2.1-pro-free"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        destination.write_bytes(resp.read())
    if destination.stat().st_size < 256:
        raise ValueError("Fish TTS nevrátilo zvuk")



def speak_streaming(text, api_key, voice, speaker=SPEAKER, *, on_first_audio=None):
    """Feed the HTTP TTS byte stream into mpg123 as soon as audio arrives.

    Fish POST /v1/tts already returns chunked audio. No new endpoint or
    unverified request field is required. Streaming does not bypass HENK.
    Only MP3 byte streams go to the player, never a shell or transcript.
    """
    payload = json.dumps({"text": text, "reference_id": voice, "format": "mp3"},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(TTS_URL, data=payload, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "model": "s2.1-pro-free"})
    with urllib.request.urlopen(req, timeout=120) as response:
        # Avoid launching mpg123 for HTTP error bodies or unsupported formats.
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and ("json" in content_type or "text/" in content_type):
            raise ValueError("Fish TTS nevrátil zvukový stream")
        read_chunk = getattr(response, "read1", response.read)
        first_chunk = read_chunk(4096)
        if not first_chunk:
            raise ValueError("Fish TTS vrátil prázdný zvuk")
        decoder = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', 'pipe:0',
                                    '-f', 's16le', '-ar', '24000', '-ac', '1', 'pipe:1'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        player = subprocess.Popen(['aplay', '-q', '-D', speaker, '-t', 'raw', '-f', 'S16_LE',
                                   '-r', '24000', '-c', '1'], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        errors = []
        def feed():
            try:
                decoder.stdin.write(first_chunk)
                while True:
                    chunk = read_chunk(4096)
                    if not chunk:
                        break
                    decoder.stdin.write(chunk)
                decoder.stdin.close()
            except (OSError, ValueError) as error:
                errors.append(error)
                decoder.stdin.close()
        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        try:
            first = True
            while True:
                chunk = decoder.stdout.read1(4096)
                if not chunk:
                    break
                player.stdin.write(chunk)
                player.stdin.flush()
                if first:
                    first = False
                    if on_first_audio:
                        on_first_audio()
            player.stdin.close()
            feeder.join(timeout=120)
            decoder_status = decoder.wait(timeout=120)
            status = player.wait(timeout=120)
            if first or status or decoder_status or errors or feeder.is_alive():
                raise RuntimeError('Přehrávání Fish Audio selhalo')
        except BaseException:
            if player.poll() is None:
                player.kill()
            if decoder.poll() is None:
                decoder.kill()
            player.wait()
            decoder.wait()
            raise
        finally:
            decoder.stdout.close()


# HENK's informational responses may carry an internal status heading.
# Strip it ONLY at the start of a spoken answer; retain actual warnings,
# pending approvals and error information unchanged.
INFORMATIONAL_HEADER = re.compile(
    r"^\s*Odpověď bez provedení operace\s*:\s*", re.IGNORECASE
)


def spoken_reply(text):
    """Read technical HENK observations naturally, without inventing a result.

    Render only a recognized, explicitly VERIFIED read-only observation.
    Any approval request, unknown operation or arbitrary JSON remains intact.
    """
    result = INFORMATIONAL_HEADER.sub("", text, count=1).strip()
    if not result.startswith("Skutečně ověřený výsledek:"):
        return result
    match = re.match(r"^Skutečně ověřený výsledek:\s*(\{[^{}]{1,4000}\})", result, re.S)
    if not match:
        return result
    try:
        observation = json.loads(match.group(1))
    except (ValueError, TypeError):
        return result
    if (not isinstance(observation, dict)
            or observation.get("action") != "hub.clock"
            or observation.get("status") != "HOST_OBSERVATIONS_VERIFIED"):
        return result
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        instant = datetime.fromisoformat(observation["observed_at"])
        if instant.tzinfo is None:
            return result
        local = instant.astimezone(ZoneInfo("Europe/Prague"))
    except (TypeError, ValueError, KeyError):
        return result
    # A verified read-only clock check needs no internal ID or JSON read aloud.
    return f"Teď je {local.hour}:{local.minute:02d}."


def ask_henk(executable, text, session, timeout=120):
    request = {"schema_version": 1, "session_id": session, "request_id": str(uuid.uuid4()),
               "text": text, "source": "respeaker"}
    # Fixed executable path, never a transcript-derived shell command.
    command = [sys.executable, str(executable)] if executable.suffix == ".py" else [str(executable)]
    answer = call(command, input_text=json.dumps(request, ensure_ascii=False) + "\n", timeout=timeout)
    value = json.loads(answer)
    if not isinstance(value, dict) or not isinstance(value.get("reply"), str):
        raise ValueError("HENK adaptér musí vracet JSON s 'reply'")
    if value.get("status") in ("queued", "waiting_approval"):
        # No claim that an action actually happened; keep pending status audible.
        print("Stav úkolu:", value["status"])
    return spoken_reply(value["reply"])[:1000]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", type=Path, help="Executable adapter for existing HENK backend (JSON over stdin/stdout)")
    ap.add_argument("--seconds", type=int, default=7)
    ap.add_argument("--once", action="store_true", help="Record one question and exit")
    args = ap.parse_args()
    if not 2 <= args.seconds <= 30:
        ap.error("--seconds musí být 2–30")
    if not args.adapter:
        ap.error("Zatím chybí ověřený HENK backend. Nastav --adapter CESTA, žádný fiktivní endpoint nepoužijeme.")
    if not args.adapter.is_file() or not os.access(args.adapter, os.R_OK):
        ap.error("Adaptér neexistuje nebo není čitelný.")
    if args.adapter.suffix != ".py" and not os.access(args.adapter, os.X_OK):
        ap.error("Ne-Python adaptér není spustitelný.")
    api_key, voice = key(), load_voice()
    session = str(uuid.uuid4())
    with tempfile.TemporaryDirectory(prefix="respeaker-", ignore_cleanup_errors=True) as tmp:
        wav, mp3 = Path(tmp)/"input.wav", Path(tmp)/"reply.mp3"
        while True:
            if not args.once:
                try:
                    input("Stiskni Enter, promluv do mikrofonu (Ctrl+C ukončí): ")
                except EOFError:
                    break
            print("Nahrávám…", flush=True)
            subprocess.run(["arecord", "-q", "-D", CARD, "-f", "S16_LE", "-r", "16000",
                            "-c", "2", "-d", str(args.seconds), str(wav)], check=True, timeout=args.seconds+15)
            utterance = transcribe(wav, api_key)
            print("Ty:", utterance)
            reply = ask_henk(args.adapter, utterance, session)
            print("HENK:", reply)
            if reply:
                synthesize(reply, mp3, api_key, voice)
                # Synchronous playback prevents echo: no audio capture while HENK speaks.
                subprocess.run(["mpg123", "-q", "-o", "alsa", "-a", SPEAKER, str(mp3)],
                               check=True, timeout=90)
            wav.unlink(missing_ok=True)
            mp3.unlink(missing_ok=True)
            if args.once:
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nUkončeno.")
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            urllib.error.URLError, json.JSONDecodeError) as error:
        print(f"Chyba hlasového mostu: {error}", file=sys.stderr)
        sys.exit(1)
