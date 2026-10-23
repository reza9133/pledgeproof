#!/usr/bin/env python3
"""Flatten the PledgeProof sources into one deployable contract file.

GenLayer's default deploy path (the CLI, Studio's "Add From File" and most
deploy scripts) takes a single Python file per contract. The project is
split into three files for readability and testability, so this script
inlines the two library modules into ``contracts/pledge_vault.py``.

Usage:
    python scripts/bundle.py

Writes:
    dist/pledge_vault.bundle.py

The script refuses to write a bundle that would be broken: it checks that the
runner header is still the first line, that no local import survived, that
the inlined modules do not define clashing names, that the result compiles
and that it contains exactly one ``gl.Contract`` class.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "pledge_vault.py"
OUTPUT = ROOT / "dist" / "pledge_vault.bundle.py"

# Order matters: a module may only use names from modules listed before it.
LIBRARIES = [ROOT / "pledgeproof_pure.py", ROOT / "pledgeproof.py"]
LOCAL_MODULES = {path.stem for path in LIBRARIES}


class BundleError(SystemExit):
    pass


def _is_local_import(node: ast.AST) -> bool:
    return isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in LOCAL_MODULES


def _is_sdk_star_import(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.ImportFrom)
        and node.module == "genlayer"
        and any(alias.name == "*" for alias in node.names)
    )


def _top_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _library_block(path: pathlib.Path) -> tuple[str, set[str]]:
    source = path.read_text()
    tree = ast.parse(source)
    lines = source.splitlines()
    drop: set[int] = set()  # 1-based line numbers

    first = tree.body[0] if tree.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        drop.update(range(first.lineno, first.end_lineno + 1))
    for node in tree.body:
        if _is_local_import(node) or _is_sdk_star_import(node):
            drop.update(range(node.lineno, node.end_lineno + 1))

    kept = [text for number, text in enumerate(lines, start=1) if number not in drop]
    body = "\n".join(kept).strip("\n")
    block = f"# ---- inlined from {path.name} ----\n{body}\n# ---- end {path.name} ----\n"
    return block, _top_level_names(tree)


def build() -> str:
    contract_source = CONTRACT.read_text()
    contract_tree = ast.parse(contract_source)
    contract_lines = contract_source.splitlines()

    if not contract_lines or not contract_lines[0].startswith('# { "Depends"'):
        raise BundleError("the first line of the contract must be the runner header")

    blocks = []
    seen: dict[str, str] = {}
    for library in LIBRARIES:
        block, names = _library_block(library)
        for name in names:
            if name in seen:
                raise BundleError(f"name clash: {name!r} is defined in both {seen[name]} and {library.name}")
            seen[name] = library.name
        blocks.append(block)
    for name in _top_level_names(contract_tree):
        if name in seen:
            raise BundleError(f"name clash: {name!r} is defined in both {seen[name]} and {CONTRACT.name}")

    imports = [n for n in contract_tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    if not imports:
        raise BundleError("the contract has no imports to anchor the inlined code to")
    insert_after = max(n.end_lineno for n in imports)
    drop: set[int] = set()
    for node in contract_tree.body:
        if _is_local_import(node):
            drop.update(range(node.lineno, node.end_lineno + 1))

    out: list[str] = []
    for number, text in enumerate(contract_lines, start=1):
        if number not in drop:
            out.append(text)
        if number == insert_after:
            out.append("")
            out.extend("\n".join(blocks).splitlines())
            out.append("")
    result = "\n".join(out).rstrip("\n") + "\n"

    # ---- sanity checks on the final artifact ----
    if result.splitlines()[0] != contract_lines[0]:
        raise BundleError("the runner header is no longer the first line")
    final_tree = ast.parse(result)
    for node in ast.walk(final_tree):
        if _is_local_import(node):
            raise BundleError(f"a local import survived: line {node.lineno}")
    contracts = [
        node.name
        for node in final_tree.body
        if isinstance(node, ast.ClassDef)
        and any(ast.unparse(base) in ("gl.Contract", "Contract") for base in node.bases)
    ]
    if len(contracts) != 1:
        raise BundleError(f"expected exactly one gl.Contract class, found {contracts}")
    compile(result, str(OUTPUT), "exec")
    return result


def main() -> None:
    result = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(result)
    print(f"wrote {OUTPUT} ({len(result)} bytes, {result.count(chr(10))} lines)")


if __name__ == "__main__":
    try:
        main()
    except BundleError as exc:
        print(f"bundle failed: {exc}", file=sys.stderr)
        raise
