from __future__ import annotations


def register(runtime_loader) -> None:
    runtime_loader.register_module(
        name="sample_module",
        capabilities=["demo", "health"],
        hooks={"on_load": "sample_module loaded"},
        import_name="modules.sample_module",
    )
