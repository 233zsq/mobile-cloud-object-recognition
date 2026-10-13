"""Run project checks with stable paths and separate pytest collection per component."""

from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
GROUPS = (
    "core",
    "backend",
    "review",
    "ml-data",
    "ml-integration",
    "web-browser",
    "deploy",
)


def commands(group, python, node, temporary):
    def pytest(config, *args):
        return [
            python,
            "-m",
            "pytest",
            "-c",
            config,
            *args,
            "-q",
            "--tb=short",
            "--basetemp=" + str(temporary / group),
        ]

    if group == "core":
        return [
            [python, "scripts/sync-configs.py", "check"],
            pytest(
                "ml/pytest.ini",
                "tests/test_config_distribution.py",
                "tests/test_data_scripts.py",
                "tests/test_tool_boundaries.py",
                "tests/test_web_assets.py",
                "ml/tests/test_reports.py",
                "ml/tests/test_atomic_write.py",
                "ml/tests/test_manifest_io.py",
            ),
            [
                node,
                "--test",
                "web/ios/tests/core.test.cjs",
                "web/ios/tests/services.test.cjs",
                "web/tests/dashboard.test.cjs",
            ],
        ]
    if group in ("backend", "review"):
        return [pytest(group + "/pytest.ini", group + "/tests")]
    if group == "ml-data":
        return [pytest("ml/pytest.ini", "ml/tests", "-m", "not integration")]
    if group == "ml-integration":
        return [pytest("ml/pytest.ini", "ml/tests", "-m", "integration")]
    if group == "web-browser":
        return [
            [
                node,
                "--test",
                "web/ios/tests/scope.browser.cjs",
                "web/ios/tests/navigation.browser.cjs",
                "web/tests/dashboard.browser.cjs",
            ]
        ]
    return [
        pytest(
            "ml/pytest.ini",
            "tests/test_cloud_deploy.py",
            "tests/test_deployment_package.py",
            "tests/test_ios_deploy.py",
        )
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        choices=GROUPS,
        action="append",
        help="Repeat to select groups; default: core",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable in the selected component environment",
    )
    parser.add_argument(
        "--node", default="node", help="Node executable for core browser tests"
    )
    parser.add_argument(
        "--list", action="store_true", help="Print commands without running checks"
    )
    args = parser.parse_args(argv)
    groups = list(dict.fromkeys(args.group or ["core"]))
    temporary = ROOT / "tmp" / ("check-project-" + uuid.uuid4().hex)
    if not args.list:
        temporary.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "ml/src"), environment.get("PYTHONPATH", "")]
    )
    failed = []
    for group in groups:
        print("\n[" + group + "]", flush=True)
        if group == "deploy" and os.name != "posix" and not args.list:
            print(
                "Deployment checks require Linux (fcntl and Unix file permissions).",
                flush=True,
            )
            failed.append(group)
            continue
        for command in commands(group, args.python, args.node, temporary):
            print("  " + subprocess.list2cmdline(command), flush=True)
            if args.list:
                continue
            try:
                result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
            except OSError as error:
                print("Cannot start check: " + str(error), flush=True)
                failed.append(group)
                break
            if result.returncode:
                failed.append(group)
                break
    if args.list:
        return 0
    if failed:
        print("\nFailed groups: " + ", ".join(failed), flush=True)
        return 1
    print("\nPassed groups: " + ", ".join(groups), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
