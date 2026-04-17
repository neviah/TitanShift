#!/usr/bin/env python3
"""Quick test that the chat doesn't try to use Camofox tools."""

from pathlib import Path
from tests.test_smoke import TestClient
from harness.api.server import create_app

# Test with the fast local_stub backend
app = create_app(Path('.').resolve())
client = TestClient(app, normalize_runtime=False)

response = client.post('/chat', json={
    'prompt': 'browse reddit and get first post',
    'model_backend': 'local_stub'
})

result = response.json()
used_tools = result.get('used_tools', [])
print(f"Tools used: {used_tools}")

camofox_tools = [t for t in used_tools if 'camofox' in t.lower()]
if camofox_tools:
    print(f"ERROR: Camofox tools were called: {camofox_tools}")
    exit(1)
else:
    print("OK: No Camofox tools were called")
    print(f"Status: OK - Fix is working!")
