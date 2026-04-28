#!/usr/bin/env python3
import httpx
r = httpx.get('http://127.0.0.1:8000/tools')
data = r.json()
# data is a list of tools directly
if isinstance(data, list):
    tools = [t.get('name') for t in data]
else:
    tools = [t.get('name') for t in data.get('tools', [])]

print(f'Tools count: {len(tools)}')
print('First 15 tools:', tools[:15])
print('Has write_file:', 'write_file' in tools)
print('Has read_file:', 'read_file' in tools)
print('Has generate_svg_asset:', 'generate_svg_asset' in tools)
