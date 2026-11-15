#!/usr/bin/env python3
"""Offline Czech wake word + end-of-speech detector for HENK.

Vosk processes the microphone only on the HUB. Fish ASR receives a bounded
utterance after a wake phrase. Not a security/authentication mechanism.
"""
from array import array
from collections import deque
import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
import wave

RATE = 16000
CHUNK = 3200               # 100 ms mono, 16 kHz signed 16-bit
STEREO_CHUNK = CHUNK * 2  # ReSpeaker exposes 2 microphone channels
WAKE_RE = re.compile(r"(?<!\w)(?:hej\s+|cau\s+|ahoj\s+)?henk(?:u|ovi)(?!\w)")
# The installed small Czech Vosk model has NO 'henku' in its lexicon.
# It ignores out-of-vocabulary grammar entries, as confirmed on HanzHub.
# Phonetically near 'venku' IS in its vocabulary (observed on the HUB).
# Keep [unk] to avoid interpreting every noise as the wake word.
WAKE_GRAMMAR = ["hej", "venku", "čau venku", "hej venku", "[unk]"]
ALIAS_RE = re.compile(r"^(?:(?:hej|cau|ahoj)\s+)?venku(?:\s|$)")
DEFAULT_MODEL = Path.home() / ".local/share/respeaker/models/vosk-model-small-cs-0.4-rhasspy"


def normalize(text):
    text = unicodedata.normalize("NFKD", str(text)).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def build_wake_recognizer(model, rate, recognizer):
    return recognizer(model, rate, json.dumps(WAKE_GRAMMAR, ensure_ascii=False))


def activated(text):
    candidate = normalize(text)
    return bool(candidate == "hej" or WAKE_RE.search(candidate) or ALIAS_RE.search(candidate))


def wake_candidate(text):
    """Recognize requested wake words; bare hej also needs ASR confirmation."""
    return bool(re.fullmatch(r"(?:hej|venku|(?:cau|hej) venku)(?: unk)*", normalize(text)))


def has_request(text):
    """Discard an isolated wake phrase, including the phonetic alias."""
    cleaned = WAKE_RE.sub("", normalize(text))
    cleaned = ALIAS_RE.sub("", cleaned)
    return bool(cleaned.strip() and cleaned.strip() != "hej")


def confirmed_request(text):
    """A phonetic wake candidate alone must never dispatch a HENK request."""
    value = normalize(text)
    match = re.match(r"^(?:(?:hej|cau|ahoj)\s+)?(?:henku|henk|hanku|hejku)\b\s*(.*)$", value)
    if match:
        return bool(match.group(1).strip())
    return bool(re.match(r"^hej\s+(?!(?:henku|henk|hanku|hejku)\b)\S", value))


def stereo_to_mono(pcm, channel="mix"):
    """Select one microphone or average both, without phase-sensitive surprises."""
    if channel not in ("left", "right", "mix"):
        raise ValueError("Neplatný mikrofonní kanál")
    values = array("h")
    values.frombytes(pcm)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) % 2:
        raise ValueError("Nekompletní stereo snímek.")
    if channel == "mix":
        mono = array("h", ((int(values[i]) + int(values[i + 1])) // 2
                            for i in range(0, len(values), 2)))
    else:
        offset = 0 if channel == "left" else 1
        mono = array("h", (values[i] for i in range(offset, len(values), 2)))
    if sys.byteorder != "little":
        mono.byteswap()
    return mono.tobytes()


class HighPass:
    """Remove measured sub-120 Hz microphone rumble without changing ALSA."""
    def __init__(self):
        self.alpha = math.exp(-2 * math.pi * 120 / RATE)
        self.previous = 0
        self.output = 0.0

    def process(self, pcm):
        samples = array('h')
        samples.frombytes(pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        result = array('h')
        for sample in samples:
            self.output = self.alpha * (self.output + sample - self.previous)
            self.previous = sample
            result.append(max(-32768, min(32767, int(self.output))))
        if sys.byteorder != 'little':
            result.byteswap()
        return result.tobytes()


def read_exact(stream, length):
    """A pipe is allowed to return partial reads; accumulate a whole frame."""
    result = bytearray()
    while len(result) < length:
        part = stream.read(length - len(result))
        if not part:
            return bytes(result)
        result.extend(part)
    return bytes(result)


def rms(pcm):
    if not pcm:
        return 0
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    return int((sum(v * v for v in samples) / len(samples)) ** 0.5) if samples else 0


class Capture:
    """No cloud upload before wake. Bounded streaming PCM capture."""
    def __init__(self, *, max_seconds=12, min_seconds=0.5, silence_seconds=1.2,
                 threshold=650, pre_roll=1.5):
        self.max_samples = int(max_seconds * RATE)
        self.min_samples = int(min_seconds * RATE)
        self.silence_samples = int(silence_seconds * RATE)
        self.threshold = threshold
        self.pre = deque(maxlen=max(1, int(pre_roll * RATE * 2 / CHUNK)))
        self.active = False
        self.chunks = []
        self.samples = 0
        self.silent = 0
        self.speech = 0

    def feed(self, pcm, wake=False):
        """Return completed PCM bytes, or None. Wake can be in the same utterance."""
        if not self.active:
            self.pre.append(pcm)
            if not wake:
                return None
            self.active = True
            self.chunks = list(self.pre)
            self.samples = sum(len(x) // 2 for x in self.chunks)
            self.pre.clear()
        else:
            self.chunks.append(pcm)
            self.samples += len(pcm) // 2

        level = rms(pcm)
        if level >= self.threshold:
            self.speech += len(pcm) // 2
            self.silent = 0
        else:
            self.silent += len(pcm) // 2

        if self.samples >= self.max_samples or (
            self.samples >= self.min_samples and
            self.speech >= int(0.15 * RATE) and
            self.silent >= self.silence_samples
        ):
            result = b"".join(self.chunks)[:self.max_samples * 2]
            self.reset()
            return result
        return None

    def finish(self):
        if not self.active:
            return None
        result = b"".join(self.chunks)[:self.max_samples * 2]
        self.reset()
        return result

    def reset(self):
        self.active, self.chunks, self.samples = False, [], 0
        self.silent, self.speech = 0, 0
        self.pre.clear()


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(pcm)


def run(model_path, adapter, threshold, once=False, debug=False, legacy_tts=False, mic_channel="mix"):
    from vosk import KaldiRecognizer, Model, SetLogLevel
    from voice_bridge import key, load_voice, transcribe, synthesize, speak_streaming, ask_henk, SPEAKER
    from led_status import StatusLeds

    if os.environ.get('FISH_ASR_BACKEND') == 'realtime':
        from fish_realtime_asr import transcribe

    if not model_path.is_dir():
        raise ValueError(f"Chybí lokální český Vosk model: {model_path}")
    if not adapter.is_file():
        raise ValueError(f"Chybí ověřený HENK adaptér: {adapter}")
    api_key, voice = key(), load_voice()
    leds = StatusLeds(debug=debug)
    leds.set("idle")
    SetLogLevel(-1)
    model = Model(str(model_path))
    detector = build_wake_recognizer(model, RATE, KaldiRecognizer)
    capture = Capture(threshold=threshold)
    highpass = HighPass()
    wake_energy = deque(maxlen=10)
    stage_started = None
    last_voice_at = None
    last_partial = None
    hej_hits = 0
    last_meter = time.monotonic()
    session_id = str(__import__("uuid").uuid4())
    # User-specific audio data never written to Git or a persistent directory.
    command = ["arecord", "-q", "-t", "raw", "-D",
               "plughw:CARD=seeed2micvoicec,DEV=0", "-f", "S16_LE",
               "-r", str(RATE), "-c", "2", "-"]
    print("Naslouchám lokálně. Řekni „Hej“, „Hej Henku“ nebo „Čau Henku“ (Ctrl+C ukončí).", flush=True)
    with tempfile.TemporaryDirectory(prefix="henk-wake-") as tmp:
        errors_path = Path(tmp) / "recorder.stderr"
        errors = errors_path.open("w+b")
        def start_recorder():
            return subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=errors, bufsize=0)
        process = start_recorder()
        try:
            wav, mp3 = Path(tmp) / "speech.wav", Path(tmp) / "response.mp3"
            while True:
                raw = read_exact(process.stdout, STEREO_CHUNK)
                if len(raw) != STEREO_CHUNK:
                    process.wait(timeout=3)
                    errors.flush()
                    errors.seek(0)
                    detail = errors.read().decode("utf-8", errors="replace").strip()[-600:]
                    raise RuntimeError(
                        f"arecord skončil (kód {process.returncode}): "
                        + (detail or "nezískána žádná data z mikrofonu")
                    )
                block = highpass.process(stereo_to_mono(raw, channel=mic_channel))
                wake_energy.append(rms(block) >= threshold)
                if debug and time.monotonic() - last_meter >= 3:
                    print(f"[mikrofon] RMS={rms(block)} (práh {threshold})", flush=True)
                    last_meter = time.monotonic()
                was_active = capture.active
                final_wake = False
                if not was_active:
                    final_wake = detector.AcceptWaveform(block)
                    if final_wake:
                        text = json.loads(detector.Result()).get("text", "")
                    else:
                        text = json.loads(detector.PartialResult()).get("partial", "")
                    candidate = normalize(text)
                    # The requested bare "hej" is common; require stability
                    # and independently confirm the complete ASR transcript.
                    if wake_candidate(text) and sum(wake_energy) >= 3:
                        hej_hits += 1
                        ambiguous = bool(re.fullmatch(r'(?:hej|venku)(?: unk)*', candidate))
                        trigger = (not ambiguous and final_wake) or hej_hits >= 3
                    else:
                        hej_hits = 0
                        trigger = False
                else:
                    trigger = False

                if trigger and not was_active:
                    print("Možné oslovení, ověřuji…", flush=True)
                    leds.set("wake")
                    leds.set("listening")
                    stage_started = time.monotonic()
                    last_voice_at = None
                if (was_active or trigger) and rms(block) >= threshold:
                    last_voice_at = time.monotonic()
                captured = capture.feed(block, wake=trigger)
                if trigger and final_wake and has_request(text) and captured is None:
                    # Vosk can recognize a whole wake+command only after final silence.
                    captured = capture.finish()
                if captured is None:
                    continue
                detector = build_wake_recognizer(model, RATE, KaldiRecognizer)
                hej_hits = 0
                if rms(captured) < 100:
                    continue
                write_wav(wav, captured)
                stage_started = time.monotonic()
                print("Rozpoznávám požadavek přes Fish Audio…", flush=True)
                leds.set("thinking")
                try:
                    try:
                        phrase = transcribe(wav, api_key)
                    except ValueError:
                        # A language hint cannot force Fish to decode Czech.
                        # Do not give non-Czech/hallucinated text to the broker.
                        print("Oslovení nebylo potvrzeno.", flush=True)
                        if once:
                            return
                        continue
                    if debug:
                        print(f"[latence] Fish ASR {time.monotonic() - stage_started:.2f} s", flush=True)
                    stage_started = time.monotonic()
                    if not confirmed_request(phrase):
                        print("Oslovení nebo požadavek nebyly potvrzeny; nic se neodesílá.", flush=True)
                        if once:
                            return
                        continue
                    print("HENK aktivován.", flush=True)
                    reply = ask_henk(adapter, phrase, session_id)
                    if debug:
                        print(f"[latence] HENK {time.monotonic() - stage_started:.2f} s", flush=True)
                    stage_started = time.monotonic()
                    if reply:
                        if legacy_tts:
                            synthesize(reply, mp3, api_key, voice)
                            if debug:
                                print(f"[latence] Fish TTS celé audio {time.monotonic() - stage_started:.2f} s", flush=True)
                            leds.set("speaking")
                            subprocess.run(["mpg123", "-q", "-o", "alsa", "-a",
                                            SPEAKER, str(mp3)], check=True, timeout=120)
                        else:
                            def first_audio():
                                if last_voice_at is not None:
                                    print(f"[latence] konec hlasu až první PCM do přehrávače: {time.monotonic() - last_voice_at:.2f} s", flush=True)
                                if debug:
                                    print(f"[latence] Fish TTS první audio {time.monotonic() - stage_started:.2f} s", flush=True)
                                leds.set("speaking")
                            speak_streaming(reply, api_key, voice, on_first_audio=first_audio)
                except Exception:
                    leds.set("error")
                    raise
                finally:
                    leds.off()
                    wav.unlink(missing_ok=True)
                    mp3.unlink(missing_ok=True)
                    # Drop buffered audio captured while HENK was speaking:
                    # restart recorder to avoid a false wake on its own voice.
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if not once:
                        detector = build_wake_recognizer(model, RATE, KaldiRecognizer)
                        hej_hits = 0
                        errors.seek(0)
                        errors.truncate()
                        process = start_recorder()
                        highpass = HighPass()
                        wake_energy.clear()
                        leds.set("idle")
                        print("Znovu čekám na oslovení „Hej“, „Hej Henku“ nebo „Čau Henku“.", flush=True)
                if once:
                    return
        finally:
            leds.off()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            errors.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--adapter", type=Path, default=Path(__file__).with_name("henk_local_adapter.py"))
    parser.add_argument("--threshold", type=int, default=650, help="RMS hranice ticha")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--mic-channel", choices=("mix", "left", "right"), default="mix",
                        help="Zdrojový kanál ReSpeakeru (při fázovém rušení zkus left nebo right)")
    parser.add_argument("--legacy-tts", action="store_true", help="Původní režim: nejdříve celé MP3 stáhnout, pak přehrát")
    parser.add_argument("--debug", action="store_true", help="Zobrazí úroveň mikrofonu a časy")
    args = parser.parse_args()
    if not 100 <= args.threshold <= 12000:
        parser.error("threshold musí být 100–12000")
    run(args.model, args.adapter, args.threshold, args.once, args.debug, args.legacy_tts, args.mic_channel)


def _stop(_signal, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGTERM, _stop)
        main()
    except KeyboardInterrupt:
        print("\nUkončeno.")
    except Exception as error:
        print(f"Wake word: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
