#!/usr/bin/env python3
"""Debug parser to test tool call extraction."""
from harness.model.adapter import CloudOpenAIAdapter

# Create an adapter instance
adapter = CloudOpenAIAdapter(
    base_url="https://openrouter.ai/api/v1",
    default_model="google/gemini-2.5-pro",
    provider_name="OpenRouter",
)

# Test 1: Simple Gemini-style marker format
test1 = '<functions.write_file:0>{"path": "test.txt", "content": "hello"}</functions>'
print("Test 1 - Simple marker:")
print(f"  Input: {test1}")
result1 = adapter._extract_pseudo_tool_calls(test1)
print(f"  Extracted: {result1}")
if result1:
    print(f"    name={result1[0].name}, args={result1[0].arguments}")
print()

# Test 2: Nested braces in content
test2 = '<functions.write_file:0>{"path": "style.css", "content": "body { color: red; }"}</functions>'
print("Test 2 - Nested braces:")
print(f"  Input: {test2}")
result2 = adapter._extract_pseudo_tool_calls(test2)
print(f"  Extracted: {result2}")
if result2:
    print(f"    name={result2[0].name}, args={result2[0].arguments}")
print()

# Test 3: Multiline with nested braces
test3 = '''<functions.write_file:0>{"path": "style.css", "content": "body {
  color: red;
  font-size: 14px;
}"}</functions>'''
print("Test 3 - Multiline nested:")
print(f"  Input (truncated): {test3[:100]}...")
result3 = adapter._extract_pseudo_tool_calls(test3)
print(f"  Extracted: {result3}")
if result3:
    print(f"    name={result3[0].name}, args={result3[0].arguments}")
print()

# Test 4: Functions dot notation
test4 = 'functions.write_file:0 {"path": "index.html", "content": "<html></html>"}'
print("Test 4 - Functions notation:")
print(f"  Input: {test4}")
result4 = adapter._extract_pseudo_tool_calls(test4)
print(f"  Extracted: {result4}")
if result4:
    print(f"    name={result4[0].name}, args={result4[0].arguments}")
print()

print("✓ Parser tests complete")
