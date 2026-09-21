"""Pipeline classes follow one naming rule.

    class name = CamelCase(module name) + Phase + "Pipeline"

with the acronyms BWB, TK, EU and ECHR in capitals, e.g. ``tk_articles`` in
``pipelines/semantic/`` -> ``TKSemanticPipeline``. Base classes are
``<Phase>PipelineBase``. Every concrete pipeline inherits ``PipelineBase``.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

from lawgraph.pipelines.base import PipelineBase

PHASES = ("retrieve", "normalize", "semantic")
ACRONYMS = {"bwb", "tk", "eu", "echr"}


def _camel(module_name: str) -> str:
    return "".join(
        part.upper() if part in ACRONYMS else part.capitalize()
        for part in module_name.split("_")
    )


def _pipeline_classes(phase: str):
    package = importlib.import_module(f"lawgraph.pipelines.{phase}")
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"lawgraph.pipelines.{phase}.{info.name}")
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and name.endswith("Pipeline"):
                yield info.name, name, cls


@pytest.mark.parametrize("phase", PHASES)
def test_pipeline_class_names_follow_the_rule(phase: str) -> None:
    for module_name, class_name, _ in _pipeline_classes(phase):
        expected = f"{_camel(module_name)}{phase.capitalize()}Pipeline"
        assert class_name == expected, f"{phase}/{module_name}.py"


@pytest.mark.parametrize("phase", PHASES)
def test_every_pipeline_inherits_the_common_base(phase: str) -> None:
    for module_name, class_name, cls in _pipeline_classes(phase):
        assert issubclass(cls, PipelineBase), f"{phase}/{module_name}.py {class_name}"


@pytest.mark.parametrize("phase", PHASES)
def test_base_class_is_named_phase_pipeline_base(phase: str) -> None:
    module = importlib.import_module(f"lawgraph.pipelines.{phase}.base")
    assert hasattr(module, f"{phase.capitalize()}PipelineBase")
