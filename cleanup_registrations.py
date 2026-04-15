#!/usr/bin/env python3
"""Remove remaining is_camofox_browser references from tool registrations"""

with open("harness/api/server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix HTTP adapter tool registration
old_http_desc = '''                    description=(
                        "Camoufox browser automation adapter for browsing anti-bot sites. "
                        "Use action=create_tab, navigate, snapshot, or get_links. Preferred for browsing requests."
                        if is_camofox_browser
                        else description
                    ),'''

new_http_desc = '''                    description=description,'''

content = content.replace(old_http_desc, new_http_desc)

# Fix HTTP adapter capabilities
old_http_caps = '''                    capabilities=(
                        ["browser.automation", "browser.navigate", "browser.snapshot", "browser.links", "http.rest", "api.request"]
                        if is_camofox_browser
                        else ["http.rest", "api.request", "http.get", "http.post", "http.json"]
                    ),'''

new_http_caps = '''                    capabilities=["http.rest", "api.request", "http.get", "http.post", "http.json"],'''

content = content.replace(old_http_caps, new_http_caps)

# Fix CLI adapter description
old_cli_desc = '''                    description=(
                        "Camoufox server control/helper command. Use for status/start/stop style commands, not page JavaScript."
                        if is_camofox_browser
                        else description
                    ),'''

new_cli_desc = '''                    description=description,'''

content = content.replace(old_cli_desc, new_cli_desc)

# Also need to remove Camofox-specific parameters from HTTP registration
# Find and remove the Camofox-specific action/macro/search_query parameters
lines = content.split('\n')
output_lines = []
in_http_params = False
skip_camofox_param = False

for i, line in enumerate(lines):
    # Track when we're in the HTTP adapter parameters section
    if '"properties": {' in line and i > 1240 and i < 1350:
        in_http_params = True
    elif in_http_params and line.strip().startswith('},'):
        in_http_params = False
    
    # Skip Camofox-specific parameter definitions
    if in_http_params and any(x in line for x in ['"action":', '"macro":', '"search_query":', '"tab_id":', '"user_id":', '"session_key":', '"limit":', '"offset":', '"include_screenshot":']):
        # Skip this param and following lines until we hit the next comma-less line that's not part of this param
        skip_camofox_param = True
        continue
    
    if skip_camofox_param:
        if line.strip() in ['},', '},']:  # End of parameter
            skip_camofox_param = False
            continue
        elif line.strip().endswith(',') and '"type"' not in line and '"method"' not in line and '"path"' not in line and '"base_url"' not in line and '"query"' not in line and '"headers"' not in line and '"body"' not in line and '"timeout_s"' not in line and '"max_chars"' not in line:
            # Still in describe part, skip
            continue
        else:
            skip_camofox_param = False
    
    output_lines.append(line)

content = '\n'.join(output_lines)

with open("harness/api/server.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed tool registrations!")
