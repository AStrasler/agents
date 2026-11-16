"""Security defaults in shipped API templates should stay restrictive."""

import ast
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "backend-development"
    / "skills"
    / "api-design-principles"
    / "assets"
    / "rest-api-template.py"
)


def test_api_template_restricts_cors_to_local_frontend() -> None:
    tree = ast.parse(TEMPLATE.read_text(encoding="utf-8"))
    middleware = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_middleware"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "CORSMiddleware"
    ]
    assert len(middleware) == 1

    origins = next(
        keyword.value
        for keyword in middleware[0].keywords
        if keyword.arg == "allow_origins"
    )
    assert isinstance(origins, ast.List)
    assert [value.value for value in origins.elts if isinstance(value, ast.Constant)] == [
        "http://localhost:3000"
    ]
