
import ast

from code_runner import run_python_code


def validate_python_solution(code: str) -> dict:
    if not code or not code.strip():
        return {
            "valid": False,
            "reason": "The submitted solution is empty.",
        }

    # Step 1: Check Python syntax.
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return {
            "valid": False,
            "reason": f"Syntax error: {exc}",
        }

    # Step 2: Basic execution test.
    # Do not use this runner with untrusted code until
    # proper OS-level sandboxing is implemented.
    result = run_python_code(code, timeout=5)

    if not result["success"]:
        return {
            "valid": False,
            "reason": result["stderr"] or "Execution failed.",
        }

    return {
        "valid": True,
        "reason": "Syntax and basic execution checks passed.",
        "stdout": result["stdout"],
    }

"""if __name__ == "__main__":
    solution = """
"""def add(a, b):
    return a + b

print(add(2, 3))"""
"""

    result = validate_python_solution(solution)
    print(result) """
