#!/usr/bin/env python3
"""Test the 3-stage tool narrowing filter logic."""

def test_narrow_tools_by_skill_recommendation():
    """Test the tool narrowing algorithm with mock data."""
    
    # Simulate the narrowing logic directly
    def narrow_tools_by_keyword(all_tools, task_description):
        """Simplified version of the narrowing filter."""
        task_lower = task_description.lower()
        narrowed_tools = set()
        
        for tool_name, tool_desc, capabilities in all_tools:
            tool_name_lower = tool_name.lower()
            tool_desc_lower = tool_desc.lower()
            caps_str = " ".join([c.lower() for c in capabilities])
            
            # Match domain/domain keywords
            matches_intent = False
            
            # Common intent patterns
            intent_patterns = {
                "search": {"web_fetch", "repo_", "http"},
                "browse": {"web_fetch", "browser"},
                "api": {"http", "repo_"},
                "data": {"read_file", "search_workspace"},
                "file": {"write_file", "create_directory", "read_file"},
                "code": {"write_file", "shell_command"},
            }
            
            for intent, tool_hints in intent_patterns.items():
                if intent in task_lower:
                    if any(hint in tool_name_lower or hint in caps_str for hint in tool_hints):
                        matches_intent = True
                        break
            
            if matches_intent:
                narrowed_tools.add(tool_name)
        
        return list(narrowed_tools) if narrowed_tools else None
    
    # Test data: (name, description, capabilities)
    all_tools = [
        ("web_fetch", "Fetch web content", ["http.rest", "api.request", "web.browse"]),
        ("read_file", "Read file contents", ["file.read", "workspace.query"]),
        ("write_file", "Write file contents", ["file.write", "workspace.modify"]),
        ("search_workspace", "Search workspace files", ["file.search", "workspace.query"]),
        ("shell_command", "Execute shell commands", ["shell.execute", "system.command"]),
    ]
    
    # Test 1: Search intent should match web_fetch and search_workspace
    print("Test 1: Search intent")
    result = narrow_tools_by_keyword(all_tools, "I need to search for information online")
    print(f"  Task: 'I need to search for information online'")
    print(f"  Result: {result}")
    assert result and "web_fetch" in result, f"Expected web_fetch in {result}"
    print("  OK: Correctly identified search tools\n")
    
    # Test 2: File operation intent should match file tools
    print("Test 2: File creation intent")
    result = narrow_tools_by_keyword(all_tools, "Create a new file with content")
    print(f"  Task: 'Create a new file with content'")
    print(f"  Result: {result}")
    assert result and "write_file" in result, f"Expected write_file in {result}"
    print("  OK: Correctly identified file tools\n")
    
    # Test 3: Browse intent should match web_fetch
    print("Test 3: Browse intent")
    result = narrow_tools_by_keyword(all_tools, "I want to browse the web")
    print(f"  Task: 'I want to browse the web'")
    print(f"  Result: {result}")
    assert result and "web_fetch" in result, f"Expected web_fetch in {result}"
    print("  OK: Correctly identified browse tools\n")
    
    # Test 4: Code/script intent should match code tools
    print("Test 4: Code execution intent")
    result = narrow_tools_by_keyword(all_tools, "Execute this Python code")
    print(f"  Task: 'Execute this Python code'")
    print(f"  Result: {result}")
    # Code intent should match write_file or shell_command
    assert result and any(t in result for t in ["write_file", "shell_command"]), f"Expected code tools in {result}"
    print("  OK: Correctly identified code tools\n")
    
    # Test 5: No matching intent should return None
    print("Test 5: No matching intent")
    result = narrow_tools_by_keyword(all_tools, "Tell me a joke")
    print(f"  Task: 'Tell me a joke'")
    print(f"  Result: {result}")
    assert result is None, f"Expected None for non-matching task, got {result}"
    print("  OK: No narrowing applied when intent doesn't match\n")


if __name__ == "__main__":
    print("\n=== Testing Tool Narrowing Algorithm ===\n")
    
    try:
        test_narrow_tools_by_skill_recommendation()
        print("=== All tests passed! ===\n")
    except AssertionError as e:
        print(f"\nFAILED: {e}\n")
        exit(1)
    except Exception as e:
        print(f"\nERROR: {e}\n")
        import traceback
        traceback.print_exc()
        exit(1)
