#!/usr/bin/env python3
"""Test that Camofox tools are not registered."""

from pathlib import Path
import json

# Check what's in the adapters file
adapters_file = Path(".harness/repo_tool_adapters.json")
if adapters_file.exists():
    adapters = json.loads(adapters_file.read_text())
    print(f"Total adapters in file: {len(adapters)}")
    camofox = [a for a in adapters if "camofox" in str(a.get("repo_name", "")).lower()]
    print(f"Camofox adapters in file: {len(camofox)}")
    for adapter in camofox:
        print(f"  - {adapter.get('tool_name')}")
    print()

# Now test that the server doesn't register them
from harness.api.server import create_app

try:
    app = create_app(Path('.').resolve())
    print("App created successfully")
    print("Testing tool registration...\n")
    
    # Make a test request to check tools
    from tests.test_smoke import TestClient
    client = TestClient(app, normalize_runtime=False)
    
    # Try to get available tools by making a chat request
    # (This will trigger tool registration)
    response = client.post('/chat', json={
        'prompt': 'What tools do you have?',
        'model_backend': 'local_stub'
    })
    
    result = response.json()
    print(f"Chat response status: {result.get('status')}")
    
    # Check what tools were used/mentioned
    used_tools = result.get('used_tools', [])
    camofox_tools_used = [t for t in used_tools if 'camofox' in t.lower()]
    
    if camofox_tools_used:
        print(f"ERROR: Camofox tools were still used: {camofox_tools_used}")
        exit(1)
    else:
        print(f"OK: No Camofox tools were used")
        print(f"Total tools used: {len(used_tools)}")
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
