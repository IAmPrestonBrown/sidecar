"""Command line tools for Sidecar project folders."""

import argparse
import sys
from pathlib import Path

from sidecar.export import export_project
from sidecar.seed import create_from_briefs
from sidecar.sessions import import_session
from sidecar.store import DEFAULT_ROOT, StoreError, Workspace

REPO_ROOT = Path(__file__).resolve().parents[2]


def cmd_seed(ws: Workspace) -> int:
    """Create the example project from the briefs in examples/."""
    examples = REPO_ROOT / "examples"
    try:
        proj = create_from_briefs(
            ws,
            "Example study",
            (examples / "research_brief.md").read_text(),
            (examples / "outreach_brief.md").read_text(),
        )
    except StoreError as exc:
        print(f"Skipped: {exc}")
        return 0
    counts = {k: len(proj.all(k)) for k in ("hypotheses", "organizations", "people")}
    print(f"Created {proj.path} {counts}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="sidecar")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="folder that holds projects")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list projects")
    sub.add_parser("seed", help="create the example project from examples/")
    new = sub.add_parser("new", help="create a project from a research brief")
    new.add_argument("name")
    new.add_argument("--brief", required=True, help="research brief (Markdown)")
    new.add_argument("--outreach", help="outreach brief (Markdown)")
    imp = sub.add_parser("import-call", help="add a recorded coach session to a project")
    imp.add_argument("slug")
    imp.add_argument("session", help="session folder written by the coach")
    exp = sub.add_parser("export", help="write a one-file JSON and Markdown export")
    exp.add_argument("slug")
    args = parser.parse_args()

    ws = Workspace(Path(args.root))
    if args.command == "list":
        for slug in ws.slugs():
            print(f"{slug}\t{ws.project(slug).path}")
        sys.exit(0)
    if args.command == "seed":
        sys.exit(cmd_seed(ws))
    if args.command == "new":
        try:
            proj = create_from_briefs(
                ws,
                args.name,
                Path(args.brief).read_text(),
                Path(args.outreach).read_text() if args.outreach else "",
            )
        except (OSError, StoreError) as exc:
            sys.exit(str(exc))
        print(f"Created {proj.path} with {len(proj.all('hypotheses'))} hypotheses")
        sys.exit(0)
    if args.command == "import-call":
        try:
            call = import_session(ws.project(args.slug), Path(args.session))
        except StoreError as exc:
            sys.exit(str(exc))
        print(f"Imported {call.title}; its evidence is waiting in the Inbox")
        sys.exit(0)
    if args.command == "export":
        json_path, md_path = export_project(ws.project(args.slug))
        print(json_path)
        print(md_path)
        sys.exit(0)
