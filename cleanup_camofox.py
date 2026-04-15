#!/usr/bin/env python3
"""Remove Camofox-specific fallback code from server.py"""

with open("harness/api/server.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find and remove Camofox code blocks
output_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Skip: is_camofox_browser = "camofox-browser" in repo_name
    if 'is_camofox_browser = "camofox-browser" in repo_name' in line:
        i += 1
        continue
    
    # Skip: camofox_fallback_tabs: dict[str, dict[str, Any]] = {}
    if 'camofox_fallback_tabs: dict[str, dict[str, Any]] = {}' in line:
        i += 1
        continue
    
    # Skip: def _expand_camofox_macro(...) and its body
    if 'def _expand_camofox_macro' in line:
        # Skip until next function def (async def _fetch_camofox_fallback_page)
        while i < len(lines) and 'async def _fetch_camofox_fallback_page' not in lines[i]:
            i += 1
        continue
    
    # Skip: async def _fetch_camofox_fallback_page(...) and its body
    if 'async def _fetch_camofox_fallback_page' in line:
        # Skip until next function def (async def _call_camofox_api)
        while i < len(lines) and 'async def _call_camofox_api' not in lines[i]:
            i += 1
        continue
    
    # Skip: async def _call_camofox_api(...) and its body
    if 'async def _call_camofox_api' in line:
        # Skip until we find 'async def _http_handler'
        while i < len(lines) and 'async def _http_handler' not in lines[i]:
            i += 1
        continue
    
    # Remove: if is_camofox_browser: return await _call_camofox_api(...)
    if 'if is_camofox_browser:' in line:
        # Skip this line and the next (the return statement)
        i += 2
        # Also skip any blank lines after
        while i < len(lines) and lines[i].strip() == '':
            i += 1
        continue
    
    output_lines.append(line)
    i += 1

with open("harness/api/server.py", "w", encoding="utf-8") as f:
    f.writelines(output_lines)

print("Cleanup complete!")
