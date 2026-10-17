"""Guards on the `app.models` package split: small modules, complete re-exports."""

from pathlib import Path

import app.models as models
from app.db import Base

MAX_MODULE_LINES = 300


def test_no_model_module_exceeds_line_budget():
    package_dir = Path(models.__file__).parent
    sizes = {p.name: len(p.read_text().splitlines()) for p in package_dir.glob("*.py")}
    assert sizes, "app/models package has no modules"
    too_big = {name: n for name, n in sizes.items() if n > MAX_MODULE_LINES}
    assert not too_big, f"model modules over {MAX_MODULE_LINES} lines: {too_big}"


def test_package_reexports_every_mapped_class():
    mapped = {m.class_ for m in Base.registry.mappers}
    exported = {getattr(models, name) for name in models.__all__}
    assert exported == mapped
    for cls in mapped:
        assert getattr(models, cls.__name__) is cls


def test_single_declarative_base():
    for cls in (getattr(models, name) for name in models.__all__):
        assert cls.metadata is Base.metadata
