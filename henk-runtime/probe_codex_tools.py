import os
import json
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

found = []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        found.append(request)
        self.send_response(400)
        self.end_headers()
        self.wfile.write(b'{"error":"synthetic capture; no inference"}')

with tempfile.TemporaryDirectory(prefix='codex-tools-probe-') as tmp:
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:%d/v1' % server.server_port
    provider = '{name="capture",base_url="%s",wire_api="responses",requires_openai_auth=false,supports_websockets=false}' % base
    argv = ['/opt/hanzhub-v2-code-mode-runtime/codex', '--no-daemon',
            '-c', 'model_provider="capture"', '-c', 'model_providers.capture='+provider,
            '-c', 'features.shell_tool=false', '-c', 'features.unified_exec=false',
            '-c', 'features.code_mode_host=false', '-c', 'features.view_image=false',
            '-c', 'features.plugins=false', '-c', 'features.hooks=false',
            '-c', 'features.apps=false', '-c', 'features.multi_agent=false',
            '-c', 'web_search="disabled"', '-c', 'mcp_servers={}',
            'exec', '--ignore-user-config', '--ignore-rules', '--strict-config',
            '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
            '--model', 'gpt-6.1-sol', '-']
    env = {'PATH':'/usr/bin:/bin', 'HOME':tmp, 'CODEX_HOME':tmp, 'LANG':'C.UTF-8',
           'NO_PROXY':'127.0.0.1,localhost', 'no_proxy':'127.0.0.1,localhost'}
    try:
        result = subprocess.run(argv, cwd=tmp, env=env, input=b'Synthetic tool inventory only.',
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=25)
    finally:
        server.shutdown()
    if not found:
        print('NO_CAPTURE exit=%s stderr=%s' % (result.returncode, result.stderr.decode(errors='replace')[-1000:]))
        raise SystemExit(1)
    request = found[0]
    print('model:', request.get('model'))
    print('tools:', [tool.get('name') or tool.get('type') for tool in request.get('tools', [])])
    additional = [item for item in request.get('input', []) if item.get('type') == 'additional_tools']
    print('additional_tool_entries:', len(additional))
    def names(value):
        if isinstance(value, dict):
            return ([value['name']] if isinstance(value.get('name'), str) else []) + [x for child in value.values() for x in names(child)]
        if isinstance(value, list):
            return [x for child in value for x in names(child)]
        return []
    print('additional_tool_names:', names(additional))
