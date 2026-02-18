import ast
import argparse
import sys
from pathlib import Path


def collect_python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def file_to_module_name(filepath: Path, root: Path) -> str:
    rel = filepath.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
        if not parts:
            return ""
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts)


def compute_depth(filepath: Path, root: Path) -> int:
    return len(filepath.relative_to(root).parts) - 1


def build_module_registry(root: Path) -> dict[str, Path]:
    registry = {}
    for filepath in collect_python_files(root):
        name = file_to_module_name(filepath, root)
        if name:
            registry[name] = filepath
    return registry


def resolve_relative_import(
    level: int,
    module: str | None,
    names: list[str],
    current_module: str,
    known_modules: dict[str, Path],
) -> set[str]:
    parts = current_module.split(".")
    if len(parts) < level:
        return set()
    anchor_parts = parts[:-level]

    resolved = set()
    if module is not None:
        base_parts = anchor_parts + module.split(".")
        base = ".".join(base_parts)
        for name in names:
            submod = f"{base}.{name}" if name != "*" else None
            if submod and submod in known_modules:
                resolved.add(submod)
            elif base in known_modules:
                resolved.add(base)
    else:
        for name in names:
            candidate = ".".join(anchor_parts + [name])
            if candidate in known_modules:
                resolved.add(candidate)

    return resolved


def _handle_ast_import(
    node: ast.Import,
    known_modules: dict[str, Path],
    imported: set[str],
) -> None:
    for alias in node.names:
        # Generate all prefix candidates; keep the most specific one in known_modules
        name_parts = alias.name.split(".")
        best = None
        for i in range(len(name_parts), 0, -1):
            candidate = ".".join(name_parts[:i])
            if candidate in known_modules:
                best = candidate
                break
        if best:
            imported.add(best)


def _handle_ast_import_from(
    node: ast.ImportFrom,
    current_module: str,
    known_modules: dict[str, Path],
    imported: set[str],
) -> None:
    level = node.level or 0
    module = node.module
    names = [alias.name for alias in node.names]

    if level > 0:
        resolved = resolve_relative_import(level, module, names, current_module, known_modules)
        imported.update(resolved)
        return

    # Absolute import
    if module is None:
        return

    for name in names:
        submod = f"{module}.{name}"
        if submod in known_modules:
            imported.add(submod)
        elif module in known_modules:
            imported.add(module)


def parse_file_imports(
    filepath: Path,
    root: Path,
    known_modules: dict[str, Path],
) -> set[str]:
    try:
        source = filepath.read_text(errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"Warning: syntax error in {filepath}: {e}", file=sys.stderr)
        return set()
    except OSError as e:
        print(f"Warning: could not read {filepath}: {e}", file=sys.stderr)
        return set()

    current_module = file_to_module_name(filepath, root)
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _handle_ast_import(node, known_modules, imported)
        elif isinstance(node, ast.ImportFrom):
            _handle_ast_import_from(node, current_module, known_modules, imported)

    return imported


def analyze(root: Path) -> list[dict]:
    known_modules = build_module_registry(root)
    importers: dict[str, set[str]] = {mod: set() for mod in known_modules}

    for filepath in collect_python_files(root):
        current_module = file_to_module_name(filepath, root)
        if not current_module:
            continue
        rel_path = str(filepath.relative_to(root))
        imported = parse_file_imports(filepath, root, known_modules)
        for mod in imported:
            if mod == current_module:
                continue
            if mod in importers:
                importers[mod].add(rel_path)

    results = []
    for mod, filepath in known_modules.items():
        rel_path = str(filepath.relative_to(root))
        depth = compute_depth(filepath, root)
        import_count = len(importers[mod])
        score = depth * import_count
        results.append({
            "module": mod,
            "rel_path": rel_path,
            "depth": depth,
            "import_count": import_count,
            "importers": sorted(importers[mod]),
            "score": score,
        })

    return results


def format_hot_results(results: list[dict], show_importers: bool) -> None:
    if not results:
        print("No modules matched the criteria.")
        return

    score_w = max(len("Score"), max(len(str(r["score"])) for r in results))
    depth_w = max(len("Depth"), max(len(str(r["depth"])) for r in results))
    imports_w = max(len("Imports"), max(len(str(r["import_count"])) for r in results))
    module_w = max(len("Module"), max(len(r["module"]) for r in results))
    file_w = max(len("File"), max(len(r["rel_path"]) for r in results))

    header = (
        f"{'Score':>{score_w}}  {'Depth':>{depth_w}}  {'Imports':>{imports_w}}  "
        f"{'Module':<{module_w}}  {'File':<{file_w}}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    for r in results:
        row = (
            f"{r['score']:>{score_w}}  {r['depth']:>{depth_w}}  "
            f"{r['import_count']:>{imports_w}}  "
            f"{r['module']:<{module_w}}  {r['rel_path']:<{file_w}}"
        )
        print(row)
        if show_importers and r["importers"]:
            indent = score_w + 2 + depth_w + 2 + imports_w + 2
            print(f"{'':>{indent}}<- imported by:")
            for imp in r["importers"]:
                print(f"{'':>{indent + 3}}{imp}")
            print()


def format_dead_results(results: list[dict]) -> None:
    if not results:
        print("No dead modules found.")
        return

    depth_w = max(len("Depth"), max(len(str(r["depth"])) for r in results))
    module_w = max(len("Module"), max(len(r["module"]) for r in results))
    file_w = max(len("File"), max(len(r["rel_path"]) for r in results))

    header = f"{'Depth':>{depth_w}}  {'Module':<{module_w}}  {'File':<{file_w}}"
    sep = "-" * len(header)
    print(header)
    print(sep)

    for r in results:
        print(f"{r['depth']:>{depth_w}}  {r['module']:<{module_w}}  {r['rel_path']:<{file_w}}")


def format_cold_results(results: list[dict], show_importers: bool) -> None:
    if not results:
        print("No modules matched the criteria.")
        return

    depth_w = max(len("Depth"), max(len(str(r["depth"])) for r in results))
    imports_w = max(len("Imports"), max(len(str(r["import_count"])) for r in results))
    module_w = max(len("Module"), max(len(r["module"]) for r in results))
    file_w = max(len("File"), max(len(r["rel_path"]) for r in results))

    header = (
        f"{'Depth':>{depth_w}}  {'Imports':>{imports_w}}  "
        f"{'Module':<{module_w}}  {'File':<{file_w}}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    for r in results:
        row = (
            f"{r['depth']:>{depth_w}}  {r['import_count']:>{imports_w}}  "
            f"{r['module']:<{module_w}}  {r['rel_path']:<{file_w}}"
        )
        print(row)
        if show_importers and r["importers"]:
            indent = depth_w + 2 + imports_w + 2
            print(f"{'':>{indent}}<- imported by:")
            for imp in r["importers"]:
                print(f"{'':>{indent + 3}}{imp}")
            print()


def resolve_root(path_str: str) -> Path:
    root = Path(path_str).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)
    return root


def cmd_hot(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    results = analyze(root)
    filtered = [
        r for r in results
        if r["import_count"] >= args.min_imports and r["depth"] >= args.min_depth
    ]
    filtered.sort(key=lambda r: (-r["score"], -r["import_count"], r["module"]))
    format_hot_results(filtered[: args.top], show_importers=not args.no_importers)


def cmd_dead(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    results = analyze(root)
    dead = [r for r in results if r["import_count"] == 0]
    dead.sort(key=lambda r: (-r["depth"], r["module"]))
    format_dead_results(dead[: args.top])


def cmd_cold(args: argparse.Namespace) -> None:
    root = resolve_root(args.root)
    results = analyze(root)
    cold = [
        r for r in results
        if 1 <= r["import_count"] <= args.max_imports and r["depth"] >= args.min_depth
    ]
    # Fewest importers first; among ties, deepest first (most misplaced)
    cold.sort(key=lambda r: (r["import_count"], -r["depth"], r["module"]))
    format_cold_results(cold[: args.top], show_importers=not args.no_importers)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze Python import structure to find refactoring candidates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "subcommands:\n"
            "  hot   Deeply nested modules imported by many files (promote candidates)\n"
            "  dead  Modules never imported anywhere (deletion candidates)\n"
            "  cold  Modules imported by few files (consolidation candidates)\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- hot ---
    hot_p = subparsers.add_parser(
        "hot",
        help="Deeply nested modules imported by many files",
    )
    hot_p.add_argument("root", help="Root directory to analyze")
    hot_p.add_argument("--min-imports", type=int, default=2, metavar="N",
                       help="Minimum importer count (default: 2)")
    hot_p.add_argument("--min-depth", type=int, default=1, metavar="D",
                       help="Minimum directory depth (default: 1)")
    hot_p.add_argument("--top", type=int, default=20, metavar="N",
                       help="Max results to show (default: 20)")
    hot_p.add_argument("--no-importers", action="store_true",
                       help="Suppress per-row importer list")
    hot_p.set_defaults(func=cmd_hot)

    # --- dead ---
    dead_p = subparsers.add_parser(
        "dead",
        help="Modules never imported anywhere",
    )
    dead_p.add_argument("root", help="Root directory to analyze")
    dead_p.add_argument("--top", type=int, default=50, metavar="N",
                        help="Max results to show (default: 50)")
    dead_p.set_defaults(func=cmd_dead)

    # --- cold ---
    cold_p = subparsers.add_parser(
        "cold",
        help="Modules imported by few files (candidates to inline or consolidate)",
    )
    cold_p.add_argument("root", help="Root directory to analyze")
    cold_p.add_argument("--max-imports", type=int, default=3, metavar="N",
                        help="Maximum importer count (default: 3)")
    cold_p.add_argument("--min-depth", type=int, default=0, metavar="D",
                        help="Minimum directory depth (default: 0)")
    cold_p.add_argument("--top", type=int, default=20, metavar="N",
                        help="Max results to show (default: 20)")
    cold_p.add_argument("--no-importers", action="store_true",
                        help="Suppress per-row importer list")
    cold_p.set_defaults(func=cmd_cold)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
