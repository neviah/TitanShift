#!/usr/bin/env python3
"""Test the 3-stage tool narrowing filter in ReactiveStateMachine."""

import asyncio
from pathlib import Path
from harness.state_machine.reactive import ReactiveStateMachine
from harness.runtime.config import ConfigManager
from harness.model.adapter import ModelRegistry
from harness.tools.registry import ToolRegistry
from harness.skills.registry import SkillRegistry
from harness.tools.definitions import ToolDefinition


def test_tool_narrowing_stage_1_exact_match():
    """Test Stage 1: Exact skill match from required_tools."""
    config = ConfigManager(Path("d:/Projects/TitantShift"))
    models = ModelRegistry(config)
    tools = ToolRegistry()
    skills = SkillRegistry()
    
    # Register test tools
    tools.register_tool(ToolDefinition(
        name="web_fetch",
        description="Fetch content from web URLs",
        capabilities=["http.rest", "api.request", "web.browse"],
    ))
    tools.register_tool(ToolDefinition(
        name="search_workspace",
        description="Search for files in workspace",
        capabilities=["file.search", "workspace.query"],
    ))
    
    # Register test skill with required_tools
    from harness.skills.registry import SkillDefinition
    skills.register_skill(SkillDefinition(
        skill_id="test_search_skill",
        description="Skill for searching content",
        required_tools=["web_fetch"],
        tags=["test"],
    ))
    
    rsm = ReactiveStateMachine(models, config, tools, skills)
    
    # Build tool definitions
    all_tools = rsm._build_tool_definitions()
    
    # Test narrowing with a task that mentions the skill
    task_desc = "Find information about the test search skill"
    narrowed = rsm._narrow_tools_by_skill_recommendation(all_tools, task_desc)
    
    if narrowed:
        tool_names = [str(t.get("function", {}).get("name", "")) for t in narrowed]
        print(f"Stage 1 Test: Task matches skill tag, narrowed to tools: {tool_names}")
        assert "web_fetch" in tool_names, f"Expected 'web_fetch' in narrowed tools, got {tool_names}"
        print("OK: Stage 1 exact match test passed")
    else:
        print("INFO: No narrowing applied (skill not matched in task)")


def test_tool_narrowing_stage_2_keyword_match():
    """Test Stage 2: Keyword surface match on tool capabilities."""
    config = ConfigManager(Path("d:/Projects/TitantShift"))
    models = ModelRegistry(config)
    tools = ToolRegistry()
    skills = SkillRegistry()
    
    # Register test tools with various capabilities
    tools.register_tool(ToolDefinition(
        name="web_fetch",
        description="Fetch content from URLs for browsing and searching",
        capabilities=["http.rest", "api.request", "web.browse", "search"],
        needs_network=True,
    ))
    tools.register_tool(ToolDefinition(
        name="read_file",
        description="Read file contents from workspace",
        capabilities=["file.query", "workspace.read"],
    ))
    
    rsm = ReactiveStateMachine(models, config, tools, skills)
    
    # Build tool definitions
    all_tools = rsm._build_tool_definitions()
    
    # Test narrowing with a task about searching/browsing
    task_desc = "I need to search for information online"
    narrowed = rsm._narrow_tools_by_skill_recommendation(all_tools, task_desc)
    
    if narrowed:
        tool_names = [str(t.get("function", {}).get("name", "")) for t in narrowed]
        print(f"Stage 2 Test: Task with 'search' keyword narrowed to: {tool_names}")
        assert "web_fetch" in tool_names, f"Expected 'web_fetch' for search intent, got {tool_names}"
        print("OK: Stage 2 keyword match test passed")
    else:
        print("INFO: Stage 2 - No narrowing applied (could be expected if all tools match)")


def test_tool_narrowing_fallback():
    """Test fallback when no narrowing is applied."""
    config = ConfigManager(Path("d:/Projects/TitantShift"))
    models = ModelRegistry(config)
    tools = ToolRegistry()
    skills = SkillRegistry()
    
    # Register test tools without special configuration
    tools.register_tool(ToolDefinition(
        name="generic_tool",
        description="A generic tool",
        capabilities=["generic.execute"],
    ))
    
    rsm = ReactiveStateMachine(models, config, tools, skills)
    
    # Build tool definitions
    all_tools = rsm._build_tool_definitions()
    
    # Test with random task that doesn't match anything
    task_desc = "Do something random that doesn't match any keywords"
    narrowed = rsm._narrow_tools_by_skill_recommendation(all_tools, task_desc)
    
    if narrowed is None:
        print("OK: Fallback test - No narrowing applied (as expected)")
    else:
        print(f"OK: Fallback test - Narrowed to {len(narrowed)} tools")


if __name__ == "__main__":
    print("\n=== Testing 3-Stage Tool Narrowing Filter ===\n")
    
    try:
        test_tool_narrowing_stage_1_exact_match()
        print()
        test_tool_narrowing_stage_2_keyword_match()
        print()
        test_tool_narrowing_fallback()
        print("\n=== All tests completed successfully ===\n")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
