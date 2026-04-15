#!/usr/bin/env python3
"""
Test service lifecycle management and telemetry integration.
"""

import asyncio
from pathlib import Path

from harness.runtime.service_manager import ServiceManager, ServiceLaunchConfig
from harness.runtime.telemetry import TelemetryCollector, RunTelemetry


async def test_service_manager():
    """Test service manager initialization and status tracking."""
    print("\n=== Testing Service Manager ===")
    manager = ServiceManager()
    
    # Test service registration
    config = ServiceLaunchConfig(
        service_id="test_service",
        start_strategy="subprocess",
        start_command="echo startup",
        healthcheck_url="http://127.0.0.1:9377/health",
        startup_timeout_s=5.0,
    )
    manager.register_service(config)
    status = manager.get_status("test_service")
    print(f"✓ Service registered. Status: {status.status}")
    assert status.service_id == "test_service"
    assert status.status in ["stopped", "starting", "running", "failed"]
    
    # Test health check on non-running service
    is_healthy, error = await manager.check_health("test_service")
    print(f"✓ Health check returned: healthy={is_healthy}, error={error}")
    
    # Test get all statuses
    statuses = manager.get_all_statuses()
    print(f"✓ Get all statuses returned {len(statuses)} services")
    
    print("✓ Service manager tests passed")


def test_telemetry_collector():
    """Test telemetry tracking and querying."""
    print("\n=== Testing Telemetry Collector ===")
    collector = TelemetryCollector()
    
    # Create a run
    telemetry = collector.create_run("run-123", task_id="task-456")
    print(f"✓ Created run {telemetry.run_id}")
    
    # Record tool attempts
    collector.record_tool_attempt("run-123", "tool_a", is_primary=True)
    collector.record_tool_attempt("run-123", "tool_b", is_primary=False)
    print("✓ Recorded tool attempts")
    
    # Record failure and fallback
    collector.record_tool_failure("run-123", "tool_a", "Service timeout", is_primary=True)
    collector.record_fallback("run-123")
    print("✓ Recorded tool failure and fallback")
    
    # Record success
    collector.record_tool_success("run-123", "tool_b")
    print("✓ Recorded tool success")
    
    # Finalize run
    collector.finalize_run("run-123")
    print("✓ Finalized run")
    
    # Query results
    run = collector.get_run("run-123")
    assert run.primary_tool == "tool_a"
    assert run.primary_failure_reason == "Service timeout"
    assert run.fallback_used == True
    assert run.succeeded_tool == "tool_b"
    assert run.attempted_tools == ["tool_a", "tool_b"]
    print(f"✓ Query returned: primary_tool={run.primary_tool}, fallback_used={run.fallback_used}, succeeded_tool={run.succeeded_tool}")
    
    # List recent runs
    recent = collector.list_recent_runs(limit=10)
    print(f"✓ Listed {len(recent)} recent runs")
    
    # Test dict serialization
    run_dict = run.to_dict()
    assert "run_id" in run_dict
    assert "attempted_tools" in run_dict
    print("✓ Run serialization to dict succeeded")
    
    print("✓ Telemetry collector tests passed")


def test_bootstrap_context():
    """Test that RuntimeContext includes new components."""
    print("\n=== Testing Bootstrap Integration ===")
    from harness.runtime.bootstrap import RuntimeContext
    import inspect
    
    # Check that RuntimeContext has the new fields
    sig = inspect.signature(RuntimeContext)
    params = set(sig.parameters.keys())
    
    assert "service_manager" in params, "RuntimeContext missing service_manager"
    assert "telemetry" in params, "RuntimeContext missing telemetry"
    print("✓ RuntimeContext has service_manager and telemetry fields")
    
    print("✓ Bootstrap integration tests passed")


def test_schemas():
    """Test that new API schemas are defined."""
    print("\n=== Testing API Schemas ===")
    from harness.api.schemas import RunTelemetrySummary, ServiceControlRequest, ServiceStatusResponse
    
    # Create schema instances
    telemetry_schema = RunTelemetrySummary(
        run_id="test-run",
        requested_tool="tool_a",
        attempted_tools=["tool_a", "tool_b"],
        fallback_used=True,
        duration_ms=1000,
    )
    print(f"✓ RunTelemetrySummary created: {telemetry_schema.run_id}")
    
    control_req = ServiceControlRequest(action="start")
    print(f"✓ ServiceControlRequest created: {control_req.action}")
    
    status_resp = ServiceStatusResponse(
        service_id="test",
        status="running",
        uptime_s=42.5,
    )
    print(f"✓ ServiceStatusResponse created: {status_resp.status}")
    
    print("✓ API schema tests passed")


async def main():
    """Run all tests."""
    print("\n" + "="*50)
    print("SERVICE LIFECYCLE MANAGEMENT TEST SUITE")
    print("="*50)
    
    try:
        await test_service_manager()
        test_telemetry_collector()
        test_bootstrap_context()
        test_schemas()
        
        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED")
        print("="*50)
        return 0
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
