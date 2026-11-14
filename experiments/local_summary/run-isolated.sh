#!/bin/sh
# Disposable prototype: stdin/stdout only. Never bind the host filesystem or network.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
model=/opt/hanz-agent/models/llama-3.2-3b-instruct-q4_k_m.gguf
venv=/opt/hanz-agent/.venv
[ -f "$base/worker.py" ] && [ -f "$model" ] && [ -x "$venv/bin/python" ]
exec timeout -k 10s 300s bwrap --die-with-parent --new-session \
  --unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-net \
  --clearenv --setenv PATH /usr/bin:/bin --setenv HOME /tmp --setenv TMPDIR /tmp \
  --ro-bind /usr /usr --ro-bind /lib /lib \
  --dir /opt --dir /opt/hanz-agent --ro-bind "$venv" /opt/hanz-agent/.venv \
  --dir /model --ro-bind "$model" /model/model.gguf \
  --dir /work --ro-bind "$base/worker.py" /work/worker.py \
  --proc /proc --dev /dev --tmpfs /tmp --chdir /work \
  /opt/hanz-agent/.venv/bin/python -I -B /work/worker.py
