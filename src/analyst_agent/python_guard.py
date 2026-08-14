import ast


class PythonPolicyError(ValueError):
    pass


ALLOWED_MODULES = {"pandas", "numpy", "math", "statistics", "datetime"}
FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "open", "__import__", "globals", "locals", "getattr",
    "setattr", "delattr", "input", "breakpoint",
}
FORBIDDEN_ATTRIBUTES = {
    "read_csv", "read_json", "read_pickle", "read_html", "read_sql", "load", "save",
}


def validate_python_code(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise PythonPolicyError(f"Invalid Python syntax: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    raise PythonPolicyError(f"Import is not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if not node.module or node.module.split(".")[0] not in ALLOWED_MODULES:
                raise PythonPolicyError(f"Import is not allowed: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                raise PythonPolicyError(f"Call is not allowed: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRIBUTES:
                raise PythonPolicyError(f"Method is not allowed: {node.func.attr}")
    return code
