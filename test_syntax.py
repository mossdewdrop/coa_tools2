import py_compile
import sys

try:
    py_compile.compile(r'D:\Github\coa_tools2\coa_tools2\operators\exporter\export_dragonbones.py', doraise=True)
    print("Syntax OK")
except py_compile.PyCompileError as e:
    print(f"Syntax Error: {e}")
    sys.exit(1)
