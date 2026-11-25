"""Compare one confirmed scoped change with a Markdown checklist; never write files."""
import argparse
from pathlib import Path


def cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def compare(text, scope, old, new):
    """An optional fast path for tables with 用例, 适用对象 and 验收动作 columns."""
    header = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            header = None
            continue
        values = cells(line)
        if {"用例", "适用对象", "验收动作"} <= set(values):
            header = values
            continue
        if not header or len(values) != len(header) or all(
            not value.strip("-: ") for value in values
        ):
            continue
        row = dict(zip(header, values))
        action, audience = row["验收动作"], row["适用对象"]
        if old not in action and new not in action:
            continue
        # Audience labels are free text. Only an exact match establishes scope.
        if audience != scope:
            result = "核对人群范围"
        elif old in action:
            result = "核对旧表述"
        else:
            result = "已出现新表述"
        yield number, row["用例"], result, audience, action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    for name in ("scope", "old", "new"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    if any(not value.strip() for value in (args.scope, args.old, args.new)) or args.old == args.new:
        parser.error("Specify a scope and two distinct, nonempty phrases.")
    found = False
    for number, case, kind, audience, action in compare(
        args.file.read_text(encoding="utf-8-sig"), args.scope, args.old, args.new
    ):
        found = True
        print(f"{args.file}:{number} [{kind}] {case} | {audience} | {action}")
    if not found:
        print("没有匹配的表格行；请阅读原文检查同义表达和非表格内容。")


if __name__ == "__main__":
    main()
