#!/usr/bin/env python3
"""Test that the chat handles the Reddit browsing scenario correctly."""

from pathlib import Path
import json
from tests.test_smoke import TestClient
from harness.api.server import create_app

# This is the prompt from your screenshot
prompt = """If the file \"reddit.txt\" does not exist in our workspace directory, then create it.
Use the repo camofox tool and skill for browsing. and go to reddit.
use append_file tool to add exactly one new line in that text file. writing the link to the first post you see on the reddit website on a new line in that text file.
After writing, use read_file on reddit.txt and return the full final file content.
Also return the exact tools_used list."""

app = create_app(Path('.').resolve())
client = TestClient(app, normalize_runtime=False)

print("=" * 60)
print("Testing Reddit browsing scenario")
print("=" * 60)
print(f"\nPrompt: {prompt[:100]}...\n")

response = client.post('/chat', json={
    'prompt': prompt,
    'model_backend': 'lmstudio'
})

result = response.json()
print(f"Status: {result.get('status')}")
print(f"Model: {result.get('model')}")

tools_used = result.get('used_tools', [])
print(f"\nTools used: {tools_used}")

# Check if any Camofox tools were actually called
camofox_tools_called = [t for t in tools_used if 'camofox' in t.lower()]
if camofox_tools_called:
    print(f"\nERROR: Camofox tools were called: {camofox_tools_called}")
    print("This means the fix didn't work!")
    exit(1)
else:
    print(f"\nOK: No Camofox tools were called")
    if tools_used:
        print(f"Instead used: {', '.join(set(tools_used))}")

# Check the response
response_text = result.get('response', '')
if response_text:
    print(f"\nResponse (first 200 chars):")
    print(response_text[:200])
    
    # If the prompt asked to create a file, check if it was created
    if '/reddit.txt' in response_text or 'reddit.txt' in response_text:
        readme_file = Path('reddit.txt')
        if readme_file.exists():
            print(f"\nreddit.txt was created!")
            with open(readme_file) as f:
                content = f.read()
            print(f"Content: {content[:200]}")
        else:
            print(f"\nreddit.txt was NOT created (chat asked for it but tool wasn't called)")

print("\n" + "=" * 60)
print("Test complete!")
print("=" * 60)
