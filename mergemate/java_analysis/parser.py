"""
Java source parser: extracts class info, imports, type references.

Strategy: Try javalang first (AST-based), fall back to regex if not available
or if parsing fails. Never raises — returns None on any error.
"""
from __future__ import annotations

import os
import re

try:
    import javalang  # type: ignore[import]
    _HAS_JAVALANG = True
except ImportError:
    _HAS_JAVALANG = False

from mergemate.domain.models import JavaClassInfo


def parse_java_file(file_path: str, repo_root: str) -> JavaClassInfo | None:
    """
    Parse a single Java source file.
    Returns JavaClassInfo or None if parsing fails.

    Tries javalang first, falls back to regex.
    Never raises — returns None on any error.
    """
    try:
        if _HAS_JAVALANG:
            result = _parse_with_javalang(file_path, repo_root)
            if result is not None:
                return result
        return _parse_with_regex(file_path, repo_root)
    except Exception:
        return None


def parse_java_files(
    file_paths: list[str],
    repo_root: str,
) -> list[JavaClassInfo]:
    """Parse multiple Java files. Skip unparseable files silently."""
    results = []
    for fp in file_paths:
        info = parse_java_file(fp, repo_root)
        if info is not None:
            results.append(info)
    return results


# ---- javalang-based parser ----

def _parse_with_javalang(file_path: str, repo_root: str) -> JavaClassInfo | None:
    """
    Use javalang to extract class information via AST.
    """
    try:
        abs_path = os.path.join(repo_root, file_path) if not os.path.isabs(file_path) else file_path
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()

        tree = javalang.parse.parse(source)

        # Package
        package = tree.package.name if tree.package else ""

        # Imports
        imports: list[str] = []
        for imp in (tree.imports or []):
            imports.append(imp.path)

        # Class/interface/enum name from first type
        if not tree.types:
            return None

        type_decl = tree.types[0]
        class_name = type_decl.name

        # Extends
        extends: list[str] = []
        if hasattr(type_decl, "extends") and type_decl.extends:
            if isinstance(type_decl.extends, list):
                for ext in type_decl.extends:
                    extends.append(ext.name)
            else:
                extends.append(type_decl.extends.name)

        # Implements
        implements: list[str] = []
        if hasattr(type_decl, "implements") and type_decl.implements:
            for iface in type_decl.implements:
                implements.append(iface.name)

        # Annotations (class-level)
        annotations: list[str] = []
        if hasattr(type_decl, "annotations") and type_decl.annotations:
            for ann in type_decl.annotations:
                annotations.append(ann.name)

        # Collect referenced types from AST
        referenced_types = _collect_referenced_types(type_decl, imports)

        # Determine if test file
        is_test = _is_test_file(file_path, annotations, imports)

        qualified_name = _infer_qualified_name(package, class_name)

        return JavaClassInfo(
            class_name=class_name,
            qualified_name=qualified_name,
            package=package,
            file_path=file_path.replace("\\", "/"),
            is_test_class=is_test,
            imports=imports,
            extends=extends,
            implements=implements,
            referenced_types=list(set(referenced_types)),
            annotations=annotations,
        )
    except Exception:
        return None


def _collect_referenced_types(type_decl, imports: list[str]) -> list[str]:
    """
    Walk AST to collect type names referenced in fields, methods, bodies.
    """
    types: set[str] = set()

    # Simple name imports as referenced types
    for imp in imports:
        parts = imp.split(".")
        if parts:
            simple = parts[-1]
            if simple != "*":
                types.add(simple)

    try:
        # Walk all nodes in type_decl
        for path, node in type_decl:
            if isinstance(node, javalang.tree.FieldDeclaration):
                if hasattr(node, "type") and node.type and hasattr(node.type, "name"):
                    types.add(node.type.name)
            elif isinstance(node, javalang.tree.MethodDeclaration):
                # Return type
                if node.return_type and hasattr(node.return_type, "name"):
                    types.add(node.return_type.name)
                # Parameter types
                if node.parameters:
                    for param in node.parameters:
                        if hasattr(param, "type") and param.type and hasattr(param.type, "name"):
                            types.add(param.type.name)
            elif isinstance(node, javalang.tree.ClassCreator):
                if hasattr(node, "type") and node.type and hasattr(node.type, "name"):
                    types.add(node.type.name)
            elif isinstance(node, javalang.tree.MemberReference):
                if hasattr(node, "qualifier") and node.qualifier:
                    types.add(node.qualifier)
            elif isinstance(node, javalang.tree.ClassReference):
                if hasattr(node, "type") and node.type and hasattr(node.type, "name"):
                    types.add(node.type.name)
            elif isinstance(node, javalang.tree.MethodInvocation):
                if hasattr(node, "qualifier") and node.qualifier:
                    types.add(node.qualifier)
    except Exception:
        pass

    return list(types)


# ---- regex-based fallback ----

def _parse_with_regex(file_path: str, repo_root: str) -> JavaClassInfo | None:
    """
    Regex-based extraction for when javalang is unavailable or fails.
    """
    try:
        abs_path = os.path.join(repo_root, file_path) if not os.path.isabs(file_path) else file_path
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()

        lines = source.splitlines()

        # Package
        package = ""
        m = re.search(r"^\s*package\s+([\w.]+)\s*;", source, re.MULTILINE)
        if m:
            package = m.group(1)

        # Imports
        imports: list[str] = []
        for m in re.finditer(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", source, re.MULTILINE):
            imports.append(m.group(1))

        # Class name — search for class/interface/enum/record declaration
        class_name = ""
        class_match = re.search(
            r"(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+)*"
            r"(?:class|interface|enum|record)\s+(\w+)",
            source,
        )
        if class_match:
            class_name = class_match.group(1)
        else:
            # Use filename as fallback
            basename = os.path.basename(file_path)
            if basename.endswith(".java"):
                class_name = basename[:-5]

        if not class_name:
            return None

        # Extends
        extends: list[str] = []
        ext_match = re.search(r"\bextends\s+([\w.]+)(?:<[^>]+>)?", source)
        if ext_match:
            extends.append(ext_match.group(1))

        # Implements
        implements: list[str] = []
        impl_match = re.search(r"\bimplements\s+([\w.,\s<>[\]]+?)(?:\s*\{|\s+extends)", source)
        if impl_match:
            impl_str = impl_match.group(1)
            # Split by comma, strip generics and whitespace
            for part in impl_str.split(","):
                iface = re.sub(r"<[^>]+>", "", part).strip()
                if iface:
                    implements.append(iface)

        # Annotations — look for @Annotation before the class declaration
        annotations: list[str] = []
        # Find everything before the class declaration
        if class_match:
            before_class = source[:class_match.start()]
            for ann_m in re.finditer(r"@(\w+)", before_class):
                annotations.append(ann_m.group(1))

        # referenced_types for regex mode: extract simple names from imports
        referenced_types: list[str] = []
        for imp in imports:
            parts = imp.split(".")
            if parts:
                simple = parts[-1]
                if simple != "*":
                    referenced_types.append(simple)

        is_test = _is_test_file(file_path, annotations, imports)
        qualified_name = _infer_qualified_name(package, class_name)

        return JavaClassInfo(
            class_name=class_name,
            qualified_name=qualified_name,
            package=package,
            file_path=file_path.replace("\\", "/"),
            is_test_class=is_test,
            imports=imports,
            extends=extends,
            implements=implements,
            referenced_types=list(set(referenced_types)),
            annotations=annotations,
        )
    except Exception:
        return None


def _infer_qualified_name(package: str, class_name: str) -> str:
    if package:
        return f"{package}.{class_name}"
    return class_name


def _is_test_file(file_path: str, annotations: list[str], imports: list[str]) -> bool:
    """
    True if:
    - path contains /test/ or /test\\ (normalized)
    - OR has @Test annotation in imports (org.junit.Test, org.junit.jupiter.api.Test)
    """
    norm = file_path.replace("\\", "/")
    if "/test/" in norm or norm.startswith("test/"):
        return True

    test_imports = {
        "org.junit.Test",
        "org.junit.jupiter.api.Test",
    }
    for imp in imports:
        if imp in test_imports:
            return True

    return False
