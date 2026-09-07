"""Extract top-level functions/classes/constants by name from a source file, in file
order, including decorators. Prints the concatenated source to stdout.

Usage: python3 scripts/_split_agent_tools_extract.py <source.py> name1 name2 name3 ...
"""

import ast
import sys


def _names_of(node):
    """Top-level names a statement defines (function/class name, or assignment targets)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def main():
    src_path = sys.argv[1]
    names = set(sys.argv[2:])
    text = open(src_path, encoding="utf-8").read()
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text, filename=src_path)

    found = {}
    for node in tree.body:
        for node_name in _names_of(node):
            if node_name in names:
                deco_list = getattr(node, "decorator_list", [])
                start = min([d.lineno for d in deco_list] + [node.lineno])
                found[node_name] = (start, node.end_lineno)

    missing = names - found.keys()
    if missing:
        print(f"MISSING NAMES: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)

    ordered = sorted(found.items(), key=lambda kv: kv[1][0])
    sys.stdout.write("\n\n".join("".join(lines[s - 1 : e]) for _, (s, e) in ordered) + "\n")


if __name__ == "__main__":
    main()
