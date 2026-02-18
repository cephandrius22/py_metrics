# py-metrics — Context for LLM Onboarding

## What this is

A single-file CLI tool that analyzes a Python codebase and surfaces modules that
are buried deep in the directory tree but imported in many places. These are
candidates to be promoted to a more accessible shared location.

**Scoring formula:** `score = depth * import_count`

High score = deeply nested AND widely imported — the sweet spot for refactoring.

---

## Project layout

```
py_metrics/
├── main.py          # entire implementation (~249 lines, stdlib only)
├── pyproject.toml   # py-metrics 0.1.0, requires-python >=3.13, no deps
└── .python-version  # 3.13
```

No packages, no tests directory, no configuration beyond `pyproject.toml`.
Everything lives in `main.py`.

---

## CLI

```
python main.py <root> [--min-imports N] [--min-depth D] [--top N] [--no-importers]
```

| Flag | Default | Meaning |
|---|---|---|
| `root` | (required) | Directory to analyze |
| `--min-imports` | 2 | Only show modules imported by at least N files |
| `--min-depth` | 1 | Only show modules at least N directory levels deep |
| `--top` | 20 | Max rows to display |
| `--no-importers` | off | Suppress the per-row "imported by" block |

---

## Output format

```
Score  Depth  Imports  Module                  File
------------------------------------------------------------
   12      3        4  services.core.engine    services/core/engine.py
                         <- imported by:
                            services/api/handler.py
                            tests/test_core.py
```

Column widths are dynamic (computed from data). With `--no-importers`, rows are
contiguous (no blank lines between them).

---

## Function map (`main.py`)

Functions are listed in dependency order (callers below callees).

| Function | Purpose |
|---|---|
| `collect_python_files(root)` | `sorted(root.rglob("*.py"))` — deterministic |
| `file_to_module_name(filepath, root)` | Path → dotted module name. `__init__.py` → strips filename; root `__init__.py` → `""` |
| `compute_depth(filepath, root)` | `len(rel.parts) - 1` — directory levels, excludes filename |
| `build_module_registry(root)` | `dict[dotted_name → Path]`; skips empty names (root `__init__`) |
| `resolve_relative_import(level, module, names, current_module, known_modules)` | Resolves `from .x import y` and `from ..pkg import z` against the registry |
| `_handle_ast_import(node, known_modules, imported)` | Handles `import a.b.c`; finds most-specific prefix present in registry |
| `_handle_ast_import_from(node, current_module, known_modules, imported)` | Dispatches absolute vs. relative `from ... import ...` |
| `parse_file_imports(filepath, root, known_modules)` | AST-walks one file; returns `set[str]` of resolved module names; warns on `SyntaxError`/`OSError` |
| `analyze(root)` | Orchestrates everything; returns `list[dict]` with keys below |
| `format_results(results, show_importers)` | Renders the ranked table to stdout |
| `main()` | argparse entry point |

### Result dict shape (from `analyze`)

```python
{
    "module":       str,        # dotted name, e.g. "pkg.core.engine"
    "rel_path":     str,        # relative file path, e.g. "pkg/core/engine.py"
    "depth":        int,        # directory levels
    "import_count": int,        # distinct files that import this module
    "importers":    list[str],  # sorted rel-paths of importing files
    "score":        int,        # depth * import_count
}
```

---

## Key design decisions

**Registry-first:** All `.py` files are registered as dotted module names before
any import parsing begins. Import resolution only succeeds for modules that exist
in the registry (i.e., in the codebase being analyzed). External imports are
silently ignored.

**Most-specific prefix for `import a.b.c`:** When a dotted import matches
multiple registry entries (e.g., both `pkg` and `pkg.core` are known), the
longest match wins. Iteration goes from full name down to single component.

**Relative import resolution:** `level` dots walk up from the current module's
dotted path by slicing `current_module.split(".")[:−level]`. Guard: if
`len(parts) < level`, return empty set instead of raising.

**Self-import guard:** In `analyze`, if the resolved module name equals the
current file's module name, it is skipped (a file importing itself doesn't count
as an external importer).

**`from pkg import name` ambiguity:** Tries `pkg.name` as a submodule first; if
not in registry, falls back to attributing the import to `pkg` itself.

---

## Edge cases

| Case | Behavior |
|---|---|
| Root-level `__init__.py` | `file_to_module_name` returns `""`; skipped in registry and as importer |
| Syntax error in a file | Warn to stderr, return `set()`, continue |
| OSError reading a file | Warn to stderr, return `set()`, continue |
| `import a.b.c` where only `a.b` is in registry | Resolves to `a.b` (most-specific match) |
| `from . import x` where `x` not in registry | Returns empty set; not counted |
| `from pkg import *` | `name == "*"`: submodule check skipped, falls back to `pkg` itself if in registry |
| No results after filtering | Prints `"No modules matched the criteria."` |
| Duplicate imports within one file | `imported` is a `set`; auto-deduplicated |

---

## How to run / test

```bash
# Smoke test (expect "No modules matched the criteria." on this repo)
python3 main.py .

# Real codebase
python3 main.py /path/to/project --min-imports 3 --top 10

# Suppress importer details
python3 main.py /path/to/project --no-importers

# Lower thresholds to see all nested modules
python3 main.py /path/to/project --min-imports 1 --min-depth 0
```

---

## What's not here (yet)

- No tests directory or test suite
- No support for namespace packages (implicit namespace packages without `__init__.py` are not registered)
- No output formats beyond stdout table (no JSON, no CSV)
- No cycle detection or graph output
- Does not follow symlinks (standard `rglob` behavior)
