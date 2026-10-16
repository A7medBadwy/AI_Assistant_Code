
import subprocess
import tempfile
import sys
from pathlib import Path


def run_python_code(code: str, timeout: int = 5) -> dict:
    """
    Run Python code with a timeout in a temporary directory.

    This is a basic local runner, NOT a secure sandbox.
    Do not use it for untrusted code.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "solution.py"
        file_path.write_text(code, encoding="utf-8")

        try:
            result = subprocess.run(
                [sys.executable, "-I", str(file_path)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds.",
                "return_code": None,
            }


"""if __name__ == "__main__":
    sample_code = """
#print("Hello from the code runner!")
#print(2 + 3)
"""

    result = run_python_code(sample_code)
    print(result)
"""