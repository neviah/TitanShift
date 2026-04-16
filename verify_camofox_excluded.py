#!/usr/bin/env python3
"""Verify Camofox tools are not in the available tool list."""

from pathlib import Path
from harness.api.server import create_app

app = create_app(Path('.').resolve())

# Get tools via FastAPI dependency
from harness.runtime.bootstrap import get_runtime
with app.app_context() if hasattr(app, 'app_context') else None:
    try:
        runtime = get_runtime()
        tools = runtime.tools.list_tools()
        tool_names = [t.name for t in tools]
        
        print(f"Total tools available: {len(tool_names)}")
        
        camofox_tools = [t for t in tool_names if 'camofox' in t.lower()]
        print(f"Camofox tools in list: {len(camofox_tools)}")
        
        if camofox_tools:
            print(f"ERROR: Found Camofox tools: {camofox_tools}")
            exit(1)
        
        print("\nAvailable tools:")
        for tool in sorted(tool_names)[:10]:
            print(f"  - {tool}")
        if len(tool_names) > 10:
            print(f"  ... and {len(tool_names) - 10} more")
            
        print("\nOK: Camofox tools are properly excluded!")
        
    except Exception as e:
        print(f"Could not verify via runtime: {e}")
        print("Trying via test client instead...")
        
        from tests.test_smoke import TestClient
        client = TestClient(app, normalize_runtime=False)
        
        # Check what tools the model sees
        response = client.post('/chat', json={
            'prompt': 'list your tools',
            'model_backend': 'local_stub'
        })
        
        result = response.json()
        used_tools = result.get('used_tools', [])
        
        print(f"Tools used in test chat: {used_tools}")
        
        camofox_in_used = [t for t in used_tools if 'camofox' in t.lower()]
        if camofox_in_used:
            print(f"ERROR: Camofox tools found: {camofox_in_used}")
            exit(1)
        
        print("OK: No Camofox tools were used in test chat")
