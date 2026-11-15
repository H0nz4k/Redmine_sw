"""Read-only reachability checks for Henk/Redmine local AI integration.

Run ON the HUB as a regular user: python3 diagnose_henk_redmine.py
No API keys, model input, service operations or configuration reads.
An HTTP response proves only that a particular route responded, not that
the LLM or whole application works.
"""
import json
import socket
import urllib.error
import urllib.request

PROBES = (
    ("ollama_tags", "http://127.0.0.1:11434/api/tags"),
    ("hanz_agent_loopback", "http://127.0.0.1:8087/health"),
    ("hanz_agent_lan", "http://192.168.1.3:8087/health"),
    ("hanz_agent_lan_models", "http://192.168.1.3:8087/v1/models"),
    ("redmine_version", "http://127.0.0.1:4091/api/version"),
)
TIMEOUT_SECONDS = 2.0


def probe(url, opener=None):
    """Check ONLY the fixed allowlisted GET route, without reading its body."""
    if url not in {target for _, target in PROBES}:
        raise ValueError("Endpoint is not on the read-only diagnostic allowlist.")
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
        return {"reachable": True, "http_status": status, "interpretation": "route_responded"}
    except urllib.error.HTTPError as exc:
        # An HTTP error still proves that an HTTP server answered.
        return {"reachable": True, "http_status": exc.code,
                "interpretation": "http_route_not_ready_or_protected"}
    except (urllib.error.URLError, TimeoutError, OSError, socket.timeout):
        return {"reachable": False, "http_status": None,
                "interpretation": "connection_failed_or_timed_out"}


def collect(opener=None):
    """Never return response bodies, headers, tokens, credentials or model prompts."""
    return {"schema_version": 1, "diagnostic_only": True,
            "checks": {name: probe(url, opener) for name, url in PROBES},
            "conclusion": "No inference contract or working AI model is verified by these checks."}


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
