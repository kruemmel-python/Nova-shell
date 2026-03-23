import io
import json
import os
import re
import runpy
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
import zipfile
from contextlib import redirect_stderr, redirect_stdout, suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nova.runtime import AtheriaVoiceRuntime
from nova_shell import AIAgentDefinition, CommandResult, CppEngine, NovaAtheriaRuntime, NovaShell, PipelineType, __version__, main, render_trend_explanation, resolve_emcc_command
from novascript import Assignment, Command, ForLoop, IfBlock, NovaInterpreter, NovaParser


class FakeHTTPResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.headers = self

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def get_content_charset(self) -> str:
        return "utf-8"

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class NovaShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_cwd = Path.cwd()
        self._temp_home = tempfile.TemporaryDirectory()
        self._home_patcher = patch("nova_shell.Path.home", return_value=Path(self._temp_home.name))
        self._home_patcher.start()
        self.shell = NovaShell()

    def tearDown(self) -> None:
        try:
            self.shell.route(f"cd {self.original_cwd}")
        finally:
            with suppress(Exception):
                self.shell._close_loop()
            with suppress(Exception):
                self._home_patcher.stop()
            with suppress(Exception):
                self._temp_home.cleanup()

    def test_python_expression(self) -> None:
        result = self.shell.route("py 1 + 2")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "3")

    def test_cli_main_version(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["--version"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"nova-shell {__version__}")

    def test_cli_main_single_command(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--no-plugins", "-c", "py 1 + 1"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "2")
        self.assertEqual(stderr.getvalue(), "")

    def test_persistent_python_context(self) -> None:
        self.shell.route("py x = 10")
        result = self.shell.route("py x + 5")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "15")

    def test_python_context_preloads_os_module(self) -> None:
        result = self.shell.route('py os.environ["NOVA_TEST_FLAG"] = "1"')
        self.assertIsNone(result.error)
        self.assertEqual(os.environ.get("NOVA_TEST_FLAG"), "1")
        os.environ.pop("NOVA_TEST_FLAG", None)

    def test_python_context_exposes_flow_state_proxy(self) -> None:
        payload = {"metadata": {"items": [{"title": "Example headline"}]}}
        self.shell.flow_state.set("last_match", json.dumps(payload, ensure_ascii=False))
        result = self.shell.route('py flow.state.get("last_match")["metadata"]["items"][0]["title"]')
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "Example headline")

    def test_render_trend_explanation_produces_written_outlook(self) -> None:
        guardian_payload = {
            "spawn_recommendations": [
                {
                    "category": "edge_ai",
                    "template": "TrendRadar",
                    "hardware_anchor": "cpu",
                    "reason": "edge-ai trend rose",
                }
            ]
        }
        trend_payload = {
            "metadata": {
                "forecast_direction": "emerging_uptrend",
                "forecast_score": 0.83,
                "confidence": 0.71,
                "trend_acceleration": 0.08,
                "history_length": 6,
                "items": [{"title": "Edge AI demand rises"}] * 4,
                "deltas": {
                    "signal_strength": 0.16,
                    "resource_pressure": 0.11,
                    "structural_tension": 0.09,
                },
            }
        }
        text = render_trend_explanation(guardian_payload, trend_payload)
        self.assertIn("ist davon auszugehen", text)
        self.assertIn("Edge-KI", text)
        self.assertIn("Forecast-Score von 0.83", text)
        self.assertIn("Guardian", text)

    def test_pipeline_to_python(self) -> None:
        result = self.shell.route("echo hello | py _.strip().upper()")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "HELLO")

    def test_pipeline_respects_quoted_pipe(self) -> None:
        result = self.shell.route('py "a|b"')
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "a|b")

    def test_pipeline_respects_escaped_quote_and_pipe_in_python_string(self) -> None:
        result = self.shell.route(r"py print('it\'s | ok')")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "it's | ok")

    def test_system_fallback(self) -> None:
        result = self.shell.route("echo ok")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "ok")

    def test_pwd_and_cd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            cd_result = self.shell.route(f"cd {target}")
            self.assertIsNone(cd_result.error)

            pwd_result = self.shell.route("pwd")
            self.assertEqual(pwd_result.output.strip(), str(target))
            self.assertEqual(pwd_result.data, str(target))

    def test_help_lists_compute_commands(self) -> None:
        result = self.shell.route("help")
        self.assertIsNone(result.error)
        self.assertIn("gpu", result.output)
        self.assertIn("data", result.output)
        self.assertIn("events", result.output)
        self.assertIn("wiki", result.output)
        self.assertIn("ns.exec", result.output)
        self.assertIn("ns.run", result.output)
        self.assertIn("watch", result.output)

    def test_wiki_build_generates_html_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "WIKI"
            output_dir = Path(tmp) / "site"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "_Sidebar.md").write_text(
                "# Wiki Navigation\n\n## Einstieg\n- [Home](./Home.md)\n- [API](./API.md)\n",
                encoding="utf-8",
            )
            (wiki_dir / "_Footer.md").write_text("Built with [Nova-shell](./Home.md)", encoding="utf-8")
            (wiki_dir / "Home.md").write_text(
                "# Home\n\n## Zweck\n\nWelcome to the [API](./API.md).\n",
                encoding="utf-8",
            )
            (wiki_dir / "API.md").write_text(
                "# API\n\n## Zweck\n\nReference page.\n",
                encoding="utf-8",
            )

            result = self.shell.route(f'wiki build --source "{wiki_dir}" --output "{output_dir}"')
            self.assertIsNone(result.error)
            payload = json.loads(result.output)
            self.assertEqual(payload["page_count"], 2)
            self.assertTrue((output_dir / "Home.html").is_file())
            self.assertTrue((output_dir / "index.html").is_file())
            self.assertTrue((output_dir / "assets" / "wiki.css").is_file())
            self.assertTrue((output_dir / "assets" / "wiki.js").is_file())
            self.assertTrue((output_dir / "assets" / "search-index.json").is_file())
            home_html = (output_dir / "Home.html").read_text(encoding="utf-8")
            self.assertIn("API.html", home_html)
            self.assertIn("Nova-shell Wiki", home_html)

    def test_wiki_serve_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "WIKI"
            output_dir = Path(tmp) / "site"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "_Sidebar.md").write_text(
                "# Wiki Navigation\n\n## Einstieg\n- [Home](./Home.md)\n",
                encoding="utf-8",
            )
            (wiki_dir / "Home.md").write_text(
                "# Home\n\n## Zweck\n\nHTML wiki runtime.\n",
                encoding="utf-8",
            )

            serve = self.shell.route(
                f'wiki serve --source "{wiki_dir}" --output "{output_dir}" --host 127.0.0.1 --port 0'
            )
            self.assertIsNone(serve.error)
            payload = json.loads(serve.output)
            self.assertTrue(payload["server"]["running"])
            body = urllib.request.urlopen(payload["url"]).read().decode("utf-8")
            self.assertIn("Nova-shell Wiki", body)
            self.assertIn("HTML wiki runtime.", body)

            stop = self.shell.route("wiki stop")
            self.assertIsNone(stop.error)
            stop_payload = json.loads(stop.output)
            self.assertFalse(stop_payload["server"]["running"])

    def test_doctor_json(self) -> None:
        result = self.shell.route("doctor json")
        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["version"], __version__)
        self.assertIn("modules", payload)

    def test_resolve_emcc_command_prefers_bundled_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrapper = root / "toolchains" / "nova-emcc.bat"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
            runtime_config = {
                "toolchains": {
                    "emscripten": {
                        "emcc_wrapper": "toolchains/nova-emcc.bat",
                    }
                }
            }
            with patch("nova_shell.sys.executable", str(root / "nova_shell.exe")):
                resolved = resolve_emcc_command(runtime_config, {"wasmtime": True})
        self.assertEqual(Path(resolved), wrapper.resolve())

    def test_read_repl_command_collects_multiline_python_block(self) -> None:
        responses = iter(
            [
                'py with open("items.csv","w",encoding="utf-8") as f:',
                '    f.write("id,name\\n1,Brot\\n")',
            ]
        )
        with patch("builtins.input", side_effect=lambda _prompt: next(responses)):
            command = self.shell._read_repl_command()
        self.assertEqual(
            command,
            'py with open("items.csv","w",encoding="utf-8") as f:\n    f.write("id,name\\n1,Brot\\n")',
        )

    def test_python_multiline_block_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "items.csv"
            command = (
                f'py with open(r"{csv_file}","w",encoding="utf-8") as f:\n'
                '    f.write("id,name,price\\n1,Brot,2.50\\n2,Käse,4.20\\n3,Apfel,1.10\\n")'
            )
            result = self.shell.route(command)
            self.assertIsNone(result.error)
            self.assertEqual(
                csv_file.read_text(encoding="utf-8"),
                "id,name,price\n1,Brot,2.50\n2,Käse,4.20\n3,Apfel,1.10\n",
            )

    def test_python_relative_file_write_uses_shell_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            self.shell.route(f"cd {target}")
            original_process_cwd = Path.cwd()

            command = (
                'py with open("items.csv","w",encoding="utf-8") as f:\n'
                '    f.write("id,name,price\\n1,Brot,2.50\\n2,Käse,4.20\\n3,Apfel,1.10\\n")'
            )
            result = self.shell.route(command)

            self.assertIsNone(result.error)
            self.assertTrue((target / "items.csv").exists())
            self.assertEqual(Path.cwd(), original_process_cwd)

    def test_data_load_csv_object_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "items.csv"
            csv_file.write_text("name,value\na,1\nb,2\n", encoding="utf-8")

            result = self.shell.route(f"data load {csv_file}")
            self.assertIsNone(result.error)
            parsed = json.loads(result.output)
            self.assertEqual(len(parsed), 2)
            self.assertEqual(result.data[0]["name"], "a")
            self.assertEqual(result.data_type, PipelineType.OBJECT_STREAM)

            piped = self.shell.route(f"data load {csv_file} | py len(_)")
            self.assertEqual(piped.output.strip(), "2")

    def test_data_load_alias_matches_data_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "items.csv"
            csv_file.write_text("name,value\na,1\nb,2\n", encoding="utf-8")

            result = self.shell.route(f"data.load {csv_file}")
            self.assertIsNone(result.error)
            parsed = json.loads(result.output)
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed[1]["name"], "b")

    def test_parallel_pipeline(self) -> None:
        result = self.shell.route("printf 'a\nb\n' | parallel py _.upper()")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip().splitlines(), ["A", "B"])

    def test_parallel_pipeline_accepts_generator_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "live-parallel.log"
            f.write_text("", encoding="utf-8")

            def writer() -> None:
                time.sleep(0.05)
                with f.open("a", encoding="utf-8") as handle:
                    handle.write("x\ny\n")

            thread = threading.Thread(target=writer)
            thread.start()
            try:
                result = self.shell.route(f"watch {f} --follow-seconds 0.2 | parallel py _.upper()")
            finally:
                thread.join()

            self.assertIsNone(result.error)
            self.assertEqual(result.output.strip().splitlines(), ["X", "Y"])

    def test_single_event_loop_reused(self) -> None:
        loop_id = id(self.shell.loop)
        self.shell.route("py 1 + 1")
        self.shell.route("py 2 + 2")
        self.assertEqual(id(self.shell.loop), loop_id)

    def test_watch_stream_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "logs.txt"
            f.write_text("ok\nerror\nwarn\n", encoding="utf-8")
            result = self.shell.route(f"watch {f} --lines 2 | py _.upper()")
            self.assertIsNone(result.error)
            self.assertEqual(result.output.strip().splitlines(), ["ERROR", "WARN"])

    def test_watch_follow_generator_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "live.log"
            f.write_text("", encoding="utf-8")

            def writer() -> None:
                time.sleep(0.08)
                with f.open("a", encoding="utf-8") as handle:
                    handle.write("error\n")

            thread = threading.Thread(target=writer)
            thread.start()
            try:
                result = self.shell.route(f"watch {f} --follow-seconds 0.25 | py _.upper()")
            finally:
                thread.join()

            self.assertIsNone(result.error)
            self.assertIn("ERROR", result.output)

    def test_generator_pipeline_materializes_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "live-2.log"
            f.write_text("", encoding="utf-8")

            def writer() -> None:
                time.sleep(0.05)
                with f.open("a", encoding="utf-8") as handle:
                    handle.write("foo\n")

            thread = threading.Thread(target=writer)
            thread.start()
            try:
                result = self.shell.route(f"watch {f} --follow-seconds 0.2 | py _.upper() | py _.strip()")
            finally:
                thread.join()

            self.assertIsNone(result.error)
            self.assertEqual(result.output.strip(), "FOO")

    def test_events_last(self) -> None:
        self.shell.route("py 40 + 2")
        event_result = self.shell.route("events last")
        self.assertIsNone(event_result.error)
        payload = json.loads(event_result.output)
        self.assertIn("stage", payload)

    def test_events_stats(self) -> None:
        self.shell.route("py 1 + 1")
        self.shell.route("py 2 + 2")
        stats_result = self.shell.route("events stats")
        self.assertIsNone(stats_result.error)
        stats = json.loads(stats_result.output)
        self.assertGreaterEqual(stats["count"], 2)
        self.assertIn("duration_ms_avg", stats)
        self.assertIn("rows_processed_total", stats)

    def test_data_load_arrow_mode_missing_dependency_or_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "items.csv"
            csv_file.write_text("name,value\na,1\n", encoding="utf-8")
            result = self.shell.route(f"data load {csv_file} --arrow")
            if result.error is None:
                self.assertIn("ArrowTable", result.output)
            else:
                self.assertIn("pyarrow", result.error)

    def test_wasm_command_missing_dependency_or_file_error(self) -> None:
        result = self.shell.route("wasm does_not_exist.wasm")
        self.assertIsNotNone(result.error)

    def test_ai_synthesis_command(self) -> None:
        result = self.shell.route('ai "calculate csv average"')
        self.assertIsNone(result.error)
        self.assertIn("tool.call csv_load", result.output)

    def test_vision_server_lifecycle(self) -> None:
        start = self.shell.route("vision start 8877")
        self.assertIsNone(start.error)
        status = self.shell.route("vision status")
        self.assertIn("running", status.output)
        stop = self.shell.route("vision stop")
        self.assertIsNone(stop.error)

    def test_vision_briefing_ui_runs_reports_and_serves_downloads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sample_news = (root / "sample_news.json").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp).resolve()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

            self.shell.route(f"cd {root}")
            with patch.dict(
                os.environ,
                {
                    "INDUSTRY_SCAN_FILE": str(sample_news),
                    "NOVA_RESONANCE_THRESHOLD": "0.35",
                },
                clear=False,
            ):
                start = self.shell.route(f"vision start {port}")
                self.assertIsNone(start.error)
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/briefing", timeout=20) as response:
                        page = response.read().decode("utf-8")
                    self.assertIn("Trendanalyse per Web-Oberfl", page)
                    self.assertIn("Referenzkontext", page)

                    reference_file = report_dir / "briefing_context.md"
                    reference_file.write_text("Custom context for briefing.\n", encoding="utf-8")
                    form_data = urllib.parse.urlencode(
                        {
                            "topic": "AI infrastructure agent runtime",
                            "report_dir": str(report_dir),
                            "threshold": "0.35",
                            "reference_files": str(reference_file),
                            "include_default_context": "on",
                        }
                    ).encode("utf-8")
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/briefing/run",
                        data=form_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=90) as response:
                        result_page = response.read().decode("utf-8")

                    self.assertIn("Morning Briefing abgeschlossen", result_page)
                    self.assertIn("Referenzkontext", result_page)
                    self.assertIn("Ausfuehrliche Einordnung", result_page)
                    self.assertIn("rss_morning_briefing.html", result_page)
                    match = re.search(r"run_id=([a-f0-9]+)&amp;file=morning_txt", result_page)
                    self.assertIsNotNone(match)
                    run_id = match.group(1)

                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/briefing/download?run_id={run_id}&file=morning_txt",
                        timeout=20,
                    ) as response:
                        downloaded_text = response.read().decode("utf-8")
                        disposition = response.headers.get("Content-Disposition", "")
                    self.assertIn("attachment", disposition)
                    self.assertTrue(downloaded_text.strip())

                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/briefing/view?run_id={run_id}&file=morning_html",
                        timeout=20,
                    ) as response:
                        html_report = response.read().decode("utf-8")
                    self.assertIn("Nova-shell Morning Briefing", html_report)

                    for filename in (
                        "rss_resonance_report.txt",
                        "rss_resonance_report.html",
                        "rss_trend_report.txt",
                        "rss_trend_report.html",
                        "rss_morning_briefing.txt",
                        "rss_morning_briefing.html",
                    ):
                        self.assertTrue((report_dir / filename).exists(), filename)
                finally:
                    stop = self.shell.route("vision stop")
                    self.assertIsNone(stop.error)

    def test_vision_briefing_ui_supports_auto_spawn(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sample_news = (root / "sample_news.json").resolve()
        spawned_payload = {
            "dry_run": False,
            "recommendations": [
                {
                    "category": "regulation_resilience",
                    "template": "RSS_Base",
                    "hardware_anchor": "cpu",
                    "reason": "regulation trend rose",
                }
            ],
            "spawned": [
                {
                    "name": "regulation_resilience_watch_01",
                    "category": "regulation_resilience",
                    "template": "RSS_Base",
                    "hardware_anchor": "cpu",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp).resolve()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

            self.shell.route(f"cd {root}")
            with patch.dict(
                os.environ,
                {
                    "INDUSTRY_SCAN_FILE": str(sample_news),
                    "NOVA_RESONANCE_THRESHOLD": "0.35",
                },
                clear=False,
            ), patch.object(self.shell, "_spawn_guardian_recommendations_from_source", return_value=spawned_payload) as spawn_mock:
                start = self.shell.route(f"vision start {port}")
                self.assertIsNone(start.error)
                try:
                    form_data = urllib.parse.urlencode(
                        {
                            "topic": "AI infrastructure agent runtime",
                            "report_dir": str(report_dir),
                            "threshold": "0.35",
                            "auto_spawn": "on",
                            "auto_train": "on",
                        }
                    ).encode("utf-8")
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/briefing/run",
                        data=form_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=90) as response:
                        result_page = response.read().decode("utf-8")

                    self.assertIn("Auto-Spawn:</strong> aktiv", result_page)
                    self.assertIn("Auto-Training:</strong> aktiv", result_page)
                    self.assertIn("Erzeugte Sensoren", result_page)
                    self.assertIn("Training", result_page)
                    self.assertIn("Trainierte Records:", result_page)
                    self.assertIn("regulation_resilience_watch_01", result_page)
                    spawn_mock.assert_called_once()
                finally:
                    stop = self.shell.route("vision stop")
                    self.assertIsNone(stop.error)

    def test_vision_briefing_ui_can_spawn_recommendations_after_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sample_news = (root / "sample_news.json").resolve()
        spawned_payload = {
            "dry_run": False,
            "recommendations": [
                {
                    "category": "edge_ai",
                    "template": "TrendRadar",
                    "hardware_anchor": "cpu",
                    "reason": "edge-ai trend rose",
                }
            ],
            "spawned": [
                {
                    "name": "edge_ai_watch_01",
                    "category": "edge_ai",
                    "template": "TrendRadar",
                    "hardware_anchor": "cpu",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp).resolve()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

            self.shell.route(f"cd {root}")
            with patch.dict(
                os.environ,
                {
                    "INDUSTRY_SCAN_FILE": str(sample_news),
                    "NOVA_RESONANCE_THRESHOLD": "0.35",
                },
                clear=False,
            ), patch.object(self.shell, "_spawn_guardian_recommendations_from_source", return_value=spawned_payload) as spawn_mock:
                start = self.shell.route(f"vision start {port}")
                self.assertIsNone(start.error)
                try:
                    form_data = urllib.parse.urlencode(
                        {
                            "topic": "AI infrastructure agent runtime",
                            "report_dir": str(report_dir),
                            "threshold": "0.35",
                        }
                    ).encode("utf-8")
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/briefing/run",
                        data=form_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=90) as response:
                        result_page = response.read().decode("utf-8")

                    self.assertIn("Empfohlene Sensoren jetzt erzeugen", result_page)
                    match = re.search(r"name='run_id' value='([a-f0-9]+)'", result_page)
                    self.assertIsNotNone(match)
                    run_id = match.group(1)

                    spawn_form = urllib.parse.urlencode({"run_id": run_id}).encode("utf-8")
                    spawn_request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/briefing/spawn",
                        data=spawn_form,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        method="POST",
                    )
                    with urllib.request.urlopen(spawn_request, timeout=90) as response:
                        spawned_page = response.read().decode("utf-8")

                    self.assertIn("Erzeugte Sensoren", spawned_page)
                    self.assertIn("edge_ai_watch_01", spawned_page)
                    spawn_mock.assert_called_once()
                finally:
                    stop = self.shell.route("vision stop")
                    self.assertIsNone(stop.error)

    def test_remote_command_usage_error(self) -> None:
        result = self.shell.route("remote")
        self.assertIsNotNone(result.error)

    def test_fabric_put_get_roundtrip(self) -> None:
        put_result = self.shell.route("fabric put hello-fabric")
        self.assertIsNone(put_result.error)
        handle = put_result.output.strip()
        get_result = self.shell.route(f"fabric get {handle}")
        self.assertIsNone(get_result.error)
        self.assertEqual(get_result.output.strip(), "hello-fabric")

    def test_fabric_get_reads_zero_arrow_handle_as_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "items.csv"
            csv_file.write_text("id,name,price\n1,Brot,2.50\n2,Käse,4.20\n", encoding="utf-8")
            put_result = self.shell.route(f"zero put-arrow {csv_file}")
            if put_result.error is not None:
                self.assertIn("pyarrow", put_result.error)
                return
            handle = json.loads(put_result.output)["handle"]
            get_result = self.shell.route(f"fabric get {handle}")
            self.assertIsNone(get_result.error)
            payload = json.loads(get_result.output)
            self.assertEqual(payload["type"], "arrow_table")
            self.assertEqual(payload["rows"], 2)
            self.assertEqual(payload["columns"], ["id", "name", "price"])

    def test_guard_policy_blocks_sys(self) -> None:
        self.shell.route("guard set minimal")
        result = self.shell.route("sys echo blocked")
        self.assertIsNotNone(result.error)
        self.assertIn("blocks", result.error)
        self.shell.route("guard set open")

    def test_secure_command_with_policy(self) -> None:
        blocked = self.shell.route("secure minimal sys echo no")
        self.assertIsNotNone(blocked.error)
        allowed = self.shell.route("secure open py 1 + 1")
        self.assertIsNone(allowed.error)
        self.assertEqual(allowed.output.strip(), "2")

    def test_on_file_trigger_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trigger = Path(tmp) / "in.csv"

            def writer() -> None:
                time.sleep(0.08)
                trigger.write_text("a,b\n1,2\n", encoding="utf-8")

            thread = threading.Thread(target=writer)
            thread.start()
            try:
                cmd = f'on file "{tmp}/*.csv" --timeout 1.0 "py _.endswith(\'.csv\')"'
                result = self.shell.route(cmd)
            finally:
                thread.join()

            self.assertIsNone(result.error)
            self.assertEqual(result.output.strip(), "True")

    def test_pack_creates_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "sample.ns"
            out = Path(tmp) / "bundle.npx"
            script.write_text("py 1+1\n", encoding="utf-8")
            result = self.shell.route(f"pack {script} --output {out}")
            self.assertIsNone(result.error)
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out) as zf:
                self.assertIn("manifest.json", zf.namelist())

    def test_observe_run_returns_trace(self) -> None:
        result = self.shell.route("observe run py 2 + 3")
        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertIn("trace_id", payload)

    def test_pipeline_graph_fuses_consecutive_python_stages(self) -> None:
        graph = self.shell._build_pipeline_graph(["py _.strip()", "py _.upper()", "sys echo ok"])
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(graph.nodes[0].name, "py_chain")
        self.assertEqual(graph.nodes[0].stages, ["py _.strip()", "py _.upper()"])

    def test_event_contains_node_name(self) -> None:
        self.shell.route("py 1 + 1 | py _ + 1")
        event_result = self.shell.route("events last")
        payload = json.loads(event_result.output)
        self.assertIn("node", payload)

    def test_gpu_command_missing_file_or_dependency(self) -> None:
        result = self.shell.route("gpu does_not_exist.cl")
        self.assertIsNotNone(result.error)

    def test_novascript_parser_builds_ast(self) -> None:
        parser = NovaParser()
        nodes = parser.parse(
            """
files = sys printf 'a\\nb\\n'
for f in files:
    py $f
if len(files_lines) > 0:
    py 1 + 1
""".strip()
        )
        self.assertIsInstance(nodes[0], Assignment)
        self.assertIsInstance(nodes[1], ForLoop)
        self.assertIsInstance(nodes[2], IfBlock)

    def test_novascript_parser_treats_arrow_as_contract_only_when_separated(self) -> None:
        parser = NovaParser()
        nodes = parser.parse(
            """
py "<!-- guardian_recommend -->"
py 1 + 1 -> text
""".strip()
        )
        self.assertIsInstance(nodes[0], Command)
        self.assertIsNone(nodes[0].output_contract)
        self.assertEqual(nodes[1].output_contract, "text")

    def test_novascript_interpreter_executes_loop_and_if(self) -> None:
        parser = NovaParser()
        nodes = parser.parse(
            """
files = sys printf 'x\\ny\\n'
for f in files:
    py $f
if len(files_lines) == 2:
    py 99
""".strip()
        )
        interpreter = NovaInterpreter(self.shell)
        output = interpreter.execute(nodes)
        self.assertEqual(output.strip(), "99")

    def test_ns_exec_inline_script(self) -> None:
        result = self.shell.route("ns.exec values = sys printf '1\\n2\\n'; for v in values:;     py $v")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip().splitlines(), ["1", "2"])

    def test_ns_run_script_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script_file = Path(tmp) / "sample.ns"
            script_file.write_text("x = py 5*5\npy $x\n", encoding="utf-8")
            result = self.shell.route(f"ns.run {script_file}")
            self.assertIsNone(result.error)
            self.assertEqual(result.output.strip(), "25")

    def test_ns_run_supports_comments_range_and_object_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script_file = Path(tmp) / "watch_test.ns"
            script_file.write_text(
                "# comment\n"
                "watch resonance_detected:\n"
                '    match_data = flow state get "last_match"\n'
                '    analysis = py $match_data + "!"\n'
                '    py "ALARM:" + $analysis\n'
                "for i in range(2):\n"
                '    current_scan = py {"score": 0.9, "summary": "hit"}\n'
                "    if float(current_scan.score) > 0.85:\n"
                '        flow state set "last_match" $current_scan\n'
                '        ns.emit resonance_detected "TRUE"\n'
                "    sys sleep 0\n",
                encoding="utf-8",
            )
            result = self.shell.route(f"ns.run {script_file}")

        self.assertIsNone(result.error)
        self.assertIn("ALARM:", result.output)
        self.assertEqual(result.output.count("ALARM:"), 2)

    def test_ns_check_uses_shell_cwd_for_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            script_file = target / "sample.ns"
            script_file.write_text("rows: object_stream = data load items.csv\n", encoding="utf-8")
            self.shell.route(f"cd {target}")
            result = self.shell.route("ns.check sample.ns")
            self.assertIsNone(result.error)
            payload = json.loads(result.output)
            self.assertGreaterEqual(payload["contracts"], 1)

    def test_ns_check_morning_briefing_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.shell.route(f"cd {root}")
        result = self.shell.route("ns.check morning_briefing.ns")
        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertGreaterEqual(payload["commands"], 10)

    def test_ns_run_morning_briefing_generates_html_reports(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sample_news = (root / "sample_news.json").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp).resolve()
            self.shell.route(f"cd {root}")
            with patch.dict(
                os.environ,
                {
                    "INDUSTRY_SCAN_FILE": str(sample_news),
                    "NOVA_BRIEFING_REPORT_DIR": str(report_dir),
                    "INDUSTRY_TREND_STATE": str(report_dir / "trend_state.json"),
                    "NOVA_RESONANCE_THRESHOLD": "0.35",
                },
                clear=False,
            ):
                result = self.shell.route("ns.run morning_briefing.ns")

            self.assertIsNone(result.error)
            self.assertTrue((report_dir / "rss_resonance_report.html").exists())
            self.assertTrue((report_dir / "rss_trend_report.html").exists())
            self.assertTrue((report_dir / "rss_morning_briefing.html").exists())
            trend_text = (report_dir / "rss_trend_report.txt").read_text(encoding="utf-8")
            morning_text = (report_dir / "rss_morning_briefing.txt").read_text(encoding="utf-8")
            trend_html = (report_dir / "rss_trend_report.html").read_text(encoding="utf-8")
            self.assertIn("Assessment:", trend_text)
            self.assertIn("auszugehen", morning_text)
            self.assertIn("Interpretation", trend_html)

    def test_ns_run_morning_briefing_can_train_reports_into_memory_and_atheria(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sample_news = (root / "sample_news.json").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp).resolve()
            self.shell.route(f"cd {root}")
            before_status = json.loads(self.shell.route("atheria status").output)
            before_records = int(before_status.get("trained_records", 0))
            with patch.dict(
                os.environ,
                {
                    "INDUSTRY_SCAN_FILE": str(sample_news),
                    "NOVA_BRIEFING_REPORT_DIR": str(report_dir),
                    "INDUSTRY_TREND_STATE": str(report_dir / "trend_state.json"),
                    "NOVA_RESONANCE_THRESHOLD": "0.35",
                    "NOVA_BRIEFING_AUTO_TRAIN": "1",
                },
                clear=False,
            ):
                result = self.shell.route("ns.run morning_briefing.ns")

            self.assertIsNone(result.error)
            training_payload = json.loads(self.shell.flow_state.get("morning_briefing.training") or "{}")
            self.assertTrue(training_payload.get("enabled"))
            self.assertGreaterEqual(int(training_payload.get("trained_records", 0)), 3)
            self.assertEqual(
                set(training_payload.get("memory_ids", [])),
                {"briefing_resonance_report", "briefing_trend_report", "briefing_morning_report"},
            )

            listing = self.shell.route("memory list --namespace morning_briefing --project rss_monitoring")
            self.assertIsNone(listing.error)
            memory_payload = json.loads(listing.output)
            ids = {item["id"] for item in memory_payload}
            self.assertTrue({"briefing_resonance_report", "briefing_trend_report", "briefing_morning_report"}.issubset(ids))

            after_status = json.loads(self.shell.route("atheria status").output)
            self.assertGreaterEqual(int(after_status.get("trained_records", 0)), before_records + 3)

    def test_ns_run_project_monitor_generates_html_and_detects_line_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_project_monitor_helper.py"
        generator_path = root / "scripts" / "generate_project_monitor_ns.py"
        generator = runpy.run_path(str(generator_path))
        ns_text = generator["build_ns_text"](helper_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            script_file = project / "nova_project_monitor.ns"
            source_dir = project / "src"
            source_dir.mkdir(parents=True, exist_ok=True)
            target_file = source_dir / "app.ts"
            target_file.write_text(
                "const a = 1;\n"
                "function renderValue() {\n"
                "  return a;\n"
                "}\n",
                encoding="utf-8",
            )
            script_file.write_text(ns_text, encoding="utf-8")

            with patch.dict(os.environ, {"NOVA_PROJECT_MONITOR_ONESHOT": "1", "NOVA_PROJECT_MONITOR_OPEN": "0"}, clear=False):
                self.shell.route(f"cd {project}")
                first = self.shell.route(f"ns.run {script_file}")
                self.assertIsNone(first.error)

            monitor_dir = project / ".nova_project_monitor"
            report_path = monitor_dir / "project_monitor_report.html"
            helper_copy = monitor_dir / "project_monitor_helper.py"
            history_path = monitor_dir / "history.json"
            self.assertTrue(report_path.is_file())
            self.assertTrue(helper_copy.is_file())
            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(history_payload["events"]), 1)
            self.assertEqual(history_payload["events"][0]["kind"], "baseline")

            target_file.write_text(
                "const a = 2;\n"
                "function renderValue() {\n"
                "  return a + 1;\n"
                "}\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"NOVA_PROJECT_MONITOR_ONESHOT": "1", "NOVA_PROJECT_MONITOR_OPEN": "0"}, clear=False):
                second = self.shell.route(f"ns.run {script_file}")
                self.assertIsNone(second.error)

            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(history_payload["events"]), 2)
            change_event = history_payload["events"][-1]
            self.assertEqual(change_event["kind"], "change")
            self.assertEqual(len(change_event["modified"]), 1)
            modified = change_event["modified"][0]
            self.assertEqual(modified["path"], "src/app.ts")
            self.assertGreaterEqual(modified["added_lines"], 1)
            self.assertGreaterEqual(modified["removed_lines"], 1)
            self.assertIn("review_agent", change_event)
            self.assertIn(change_event["review_agent"]["severity"], {"low", "medium", "high", "critical"})
            self.assertIn("Review-Agent bewertet", change_event["review_agent"]["summary"])
            self.assertEqual(change_event["review_agent"]["source"], "heuristic")
            self.assertIn("detail_page", modified)
            self.assertTrue((monitor_dir / modified["detail_page"]).is_file())
            html_body = report_path.read_text(encoding="utf-8")
            self.assertIn("src/app.ts", html_body)
            self.assertIn("Aenderung erkannt", html_body)
            self.assertIn("Review-Agent", html_body)
            self.assertIn("Datei-Hotspots", html_body)

    def test_project_monitor_limits_snapshot_text_capture_for_large_projects(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(root / "examples" / "nova_project_monitor_helper.py"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            state_dir = project / ".nova_project_monitor"
            state_dir.mkdir(parents=True, exist_ok=True)
            source_dir = project / "src"
            source_dir.mkdir(parents=True, exist_ok=True)
            large_file = source_dir / "large.ts"
            large_file.write_text(("const line = 'x';\n" * 4000), encoding="utf-8")
            with patch.dict(
                os.environ,
                {"NOVA_PROJECT_MONITOR_OPEN": "0", "NOVA_PROJECT_MONITOR_MAX_TEXT_BYTES": "128"},
                clear=False,
            ):
                payload = helper["monitor_once"](project, state_dir, runtime_status={"watch_mode": "poll"})
            self.assertTrue((state_dir / "project_monitor_report.html").is_file())
            self.assertTrue((state_dir / "latest_status.json").is_file())
            self.assertEqual(payload["runtime"]["watch_mode"], "poll")
            snapshot = json.loads((state_dir / "snapshot.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(int(snapshot.get("text_capture_omitted_files", 0)), 1)
            self.assertTrue(any(entry.get("text_state") == "text_budget_skipped" for entry in snapshot.get("files", {}).values()))
            html_body = (state_dir / "project_monitor_report.html").read_text(encoding="utf-8")
            self.assertIn("Speichergruenden", html_body)

    def test_project_monitor_excludes_runtime_state_directories(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(root / "examples" / "nova_project_monitor_helper.py"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            (project / "src").mkdir(parents=True, exist_ok=True)
            (project / "src" / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")
            (project / ".nova").mkdir(parents=True, exist_ok=True)
            (project / ".nova" / "runtime.db").write_text("internal\n", encoding="utf-8")
            (project / ".nova_lens" / "cas").mkdir(parents=True, exist_ok=True)
            (project / ".nova_lens" / "cas" / "blob").write_text("lens\n", encoding="utf-8")
            (project / ".pytest_cache").mkdir(parents=True, exist_ok=True)
            (project / ".pytest_cache" / "state").write_text("cache\n", encoding="utf-8")

            snapshot = helper["scan_project"](project)
            self.assertIn("src/app.ts", snapshot["files"])
            self.assertNotIn(".nova/runtime.db", snapshot["files"])
            self.assertNotIn(".nova_lens/cas/blob", snapshot["files"])
            self.assertNotIn(".pytest_cache/state", snapshot["files"])

    def test_ns_run_project_monitor_can_use_ai_review_provider(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_project_monitor_helper.py"
        generator_path = root / "scripts" / "generate_project_monitor_ns.py"
        generator = runpy.run_path(str(generator_path))
        ns_text = generator["build_ns_text"](helper_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            script_file = project / "nova_project_monitor.ns"
            target_file = project / "app.ts"
            target_file.write_text("const value = 1;\n", encoding="utf-8")
            script_file.write_text(ns_text, encoding="utf-8")

            with patch.dict(os.environ, {"NOVA_PROJECT_MONITOR_ONESHOT": "1", "NOVA_PROJECT_MONITOR_OPEN": "0"}, clear=False):
                self.shell.route(f"cd {project}")
                first = self.shell.route(f"ns.run {script_file}")
                self.assertIsNone(first.error)

            target_file.write_text("const value = 2;\nconst next = value + 1;\n", encoding="utf-8")
            ai_payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "severity": "high",
                                    "headline": "AI Review",
                                    "summary": "AI hat eine relevante Aenderung erkannt.",
                                    "findings": ["Dateilogik wurde sichtbar erweitert."],
                                    "recommendations": ["Fokussierten Smoke-Test ausfuehren."],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

            with patch.dict(
                os.environ,
                {
                    "NOVA_PROJECT_MONITOR_ONESHOT": "1",
                    "NOVA_PROJECT_MONITOR_OPEN": "0",
                    "NOVA_AI_PROVIDER": "openai",
                    "NOVA_AI_MODEL": "gpt-4o-mini",
                    "OPENAI_API_KEY": "test-key",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(ai_payload)):
                    second = self.shell.route(f"ns.run {script_file}")
                    self.assertIsNone(second.error)

            history_payload = json.loads((project / ".nova_project_monitor" / "history.json").read_text(encoding="utf-8"))
            change_event = history_payload["events"][-1]
            review = change_event["review_agent"]
            self.assertEqual(review["source"], "ai")
            self.assertEqual(review["provider"], "openai")
            self.assertEqual(review["headline"], "AI Review")
            self.assertEqual(review["mode"], "openai")
            self.assertIn("AI hat eine relevante Aenderung erkannt.", review["summary"])

    def test_project_monitor_prefers_atheria_before_other_ai_providers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(root / "examples" / "nova_project_monitor_helper.py"))
        resolve = helper["resolve_ai_provider_config"]
        resolve.__globals__["atheria_runtime_available"] = lambda: True

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "NOVA_PROJECT_MONITOR_AI_MODE": "auto",
                "LM_STUDIO_MODEL": "",
                "OLLAMA_MODEL": "llama3.2",
            },
            clear=False,
        ):
            payload = resolve()

        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["provider"], "atheria")
        self.assertEqual(payload["kind"], "atheria-core")
        self.assertEqual(payload["mode"], "auto")

    def test_project_monitor_can_force_specific_ai_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(root / "examples" / "nova_project_monitor_helper.py"))
        resolve = helper["resolve_ai_provider_config"]
        resolve.__globals__["atheria_runtime_available"] = lambda: True

        with patch.dict(
            os.environ,
            {
                "NOVA_PROJECT_MONITOR_AI_MODE": "ollama",
                "OLLAMA_MODEL": "llama3.2",
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ):
            ollama_payload = resolve()

        self.assertTrue(ollama_payload["enabled"])
        self.assertEqual(ollama_payload["provider"], "ollama")
        self.assertEqual(ollama_payload["mode"], "ollama")

        with patch.dict(
            os.environ,
            {
                "NOVA_PROJECT_MONITOR_AI_MODE": "openai",
                "OPENAI_API_KEY": "test-key",
                "NOVA_AI_MODEL": "gpt-4o-mini",
            },
            clear=False,
        ):
            openai_payload = resolve()

        self.assertTrue(openai_payload["enabled"])
        self.assertEqual(openai_payload["provider"], "openai")
        self.assertEqual(openai_payload["mode"], "openai")

    def test_project_monitor_detects_build_and_test_commands(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(root / "examples" / "nova_project_monitor_helper.py"))
        detect = helper["detect_project_automation"]

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            (project / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build", "test": "vitest run"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            tests_dir = project / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_sample.py").write_text("import unittest\n", encoding="utf-8")

            commands = detect(project)

        displays = {item["display"] for item in commands}
        self.assertIn("npm run build", displays)
        self.assertIn("npm run test", displays)
        self.assertTrue(any(item["name"] == "Python Unit Tests" for item in commands))

    def test_project_monitor_resolve_watch_mode_prefers_watchdog_when_available(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(root / "examples" / "nova_project_monitor_helper.py"))
        resolve = helper["resolve_watch_mode"]
        resolve.__globals__["WATCHDOG_AVAILABLE"] = True

        with patch.dict(os.environ, {"NOVA_PROJECT_MONITOR_WATCH_MODE": "auto"}, clear=False):
            payload = resolve()

        self.assertEqual(payload["mode"], "watchdog")
        self.assertTrue(payload["available"])

        resolve.__globals__["WATCHDOG_AVAILABLE"] = False
        with patch.dict(os.environ, {"NOVA_PROJECT_MONITOR_WATCH_MODE": "watchdog"}, clear=False):
            fallback = resolve()

        self.assertEqual(fallback["mode"], "poll")
        self.assertFalse(fallback["available"])
        self.assertIn("watchdog not installed", fallback["reason"])

    def test_ns_run_project_monitor_includes_automation_results_in_report(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_project_monitor_helper.py"
        generator_path = root / "scripts" / "generate_project_monitor_ns.py"
        generator = runpy.run_path(str(generator_path))
        ns_text = generator["build_ns_text"](helper_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            script_file = project / "nova_project_monitor.ns"
            target_file = project / "app.ts"
            target_file.write_text("export const value = 1;\n", encoding="utf-8")
            (project / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build", "test": "vitest run"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            script_file.write_text(ns_text, encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "NOVA_PROJECT_MONITOR_ONESHOT": "1",
                    "NOVA_PROJECT_MONITOR_OPEN": "0",
                    "NOVA_PROJECT_MONITOR_AUTOMATION": "on",
                },
                clear=False,
            ):
                self.shell.route(f"cd {project}")
                first = self.shell.route(f"ns.run {script_file}")
                self.assertIsNone(first.error)

            target_file.write_text("export const value = 2;\nexport const next = value + 1;\n", encoding="utf-8")

            def fake_subprocess_run(command: list[str], **_: object) -> SimpleNamespace:
                display = " ".join(command)
                if display == "npm run build":
                    return SimpleNamespace(returncode=0, stdout="build ok\n", stderr="")
                if display == "npm run test":
                    return SimpleNamespace(returncode=0, stdout="tests ok\n", stderr="")
                return SimpleNamespace(returncode=1, stdout="", stderr=f"unexpected command: {display}")

            with patch.dict(
                os.environ,
                {
                    "NOVA_PROJECT_MONITOR_ONESHOT": "1",
                    "NOVA_PROJECT_MONITOR_OPEN": "0",
                    "NOVA_PROJECT_MONITOR_AUTOMATION": "on",
                },
                clear=False,
            ):
                with patch("subprocess.run", side_effect=fake_subprocess_run):
                    second = self.shell.route(f"ns.run {script_file}")
                    self.assertIsNone(second.error)

            monitor_dir = project / ".nova_project_monitor"
            history_payload = json.loads((monitor_dir / "history.json").read_text(encoding="utf-8"))
            change_event = history_payload["events"][-1]
            automation = change_event["automation"]
            self.assertTrue(automation["enabled"])
            self.assertEqual(automation["status"], "passed")
            self.assertEqual(len(automation["runs"]), 2)
            self.assertTrue(all(item["success"] for item in automation["runs"]))

            html_body = (monitor_dir / "project_monitor_report.html").read_text(encoding="utf-8")
            self.assertIn("Build und Tests", html_body)
            self.assertIn("npm run build", html_body)
            self.assertIn("tests ok", html_body)

    def test_ns_run_system_guard_generates_html_and_flags_high_risk_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_system_guard_helper.py"
        generator_path = root / "scripts" / "generate_system_guard_ns.py"
        generator = runpy.run_path(str(generator_path))
        ns_text = generator["build_ns_text"](helper_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            startup_dir = project / "startup"
            temp_dir = project / "temp"
            startup_dir.mkdir(parents=True, exist_ok=True)
            temp_dir.mkdir(parents=True, exist_ok=True)
            script_file = project / "nova_system_guard.ns"
            startup_file = startup_dir / "autorun.bat"
            startup_file.write_text("@echo off\necho safe\n", encoding="utf-8")
            script_file.write_text(ns_text, encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS": "0",
                    "NOVA_SYSTEM_GUARD_INCLUDE_PROJECT": "off",
                    "NOVA_SYSTEM_GUARD_PATHS": f"{startup_dir};{temp_dir}",
                    "NOVA_SYSTEM_GUARD_ONESHOT": "1",
                    "NOVA_SYSTEM_GUARD_OPEN": "0",
                },
                clear=False,
            ):
                self.shell.route(f"cd {project}")
                first = self.shell.route(f"ns.run {script_file}")
                self.assertIsNone(first.error)

            guard_dir = project / ".nova_system_guard"
            report_path = guard_dir / "system_guard_report.html"
            results_path = guard_dir / "system_guard_results.html"
            history_path = guard_dir / "history.json"
            status_path = guard_dir / "latest_status.json"
            helper_copy = guard_dir / "system_guard_helper.py"
            self.assertTrue(report_path.is_file())
            self.assertTrue(results_path.is_file())
            self.assertTrue(status_path.is_file())
            self.assertTrue(helper_copy.is_file())
            baseline_payload = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(baseline_payload["events"]), 1)
            self.assertEqual(baseline_payload["events"][0]["kind"], "baseline")

            startup_file.write_text("@echo off\necho suspicious\nstart powershell.exe\n", encoding="utf-8")
            (temp_dir / "dropper.exe").write_bytes(b"MZ\x90\x00payload")

            with patch.dict(
                os.environ,
                {
                    "NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS": "0",
                    "NOVA_SYSTEM_GUARD_INCLUDE_PROJECT": "off",
                    "NOVA_SYSTEM_GUARD_PATHS": f"{startup_dir};{temp_dir}",
                    "NOVA_SYSTEM_GUARD_ONESHOT": "1",
                    "NOVA_SYSTEM_GUARD_OPEN": "0",
                },
                clear=False,
            ):
                second = self.shell.route(f"ns.run {script_file}")
                self.assertIsNone(second.error)

            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(history_payload["events"]), 2)
            change_event = history_payload["events"][-1]
            self.assertEqual(change_event["kind"], "change")
            self.assertEqual(len(change_event["modified"]), 1)
            self.assertEqual(len(change_event["created"]), 1)
            modified = change_event["modified"][0]
            created = change_event["created"][0]
            self.assertEqual(modified["relative_path"], "autorun.bat")
            self.assertEqual(created["relative_path"], "dropper.exe")
            self.assertEqual(modified["scope_category"], "persistence")
            self.assertEqual(created["scope_category"], "temporary")
            self.assertGreaterEqual(modified["added_lines"], 1)
            self.assertGreaterEqual(modified["removed_lines"], 1)
            self.assertIn(change_event["review"]["severity"], {"high", "critical"})
            self.assertIn("detail_page", modified)
            detail_page_path = guard_dir / modified["detail_page"]
            self.assertTrue(detail_page_path.is_file())
            html_body = report_path.read_text(encoding="utf-8")
            results_body = results_path.read_text(encoding="utf-8")
            self.assertIn("Nova System Guard", html_body)
            self.assertIn("Letzte abgeschlossene Ergebnisseite", html_body)
            self.assertIn("Custom Startup Path", html_body)
            self.assertIn("Custom Temp Path", html_body)
            self.assertIn("autorun.bat", html_body)
            self.assertIn("dropper.exe", html_body)
            self.assertIn("Sicherheitsrelevante Aenderung erkannt", html_body)
            self.assertIn("Stabile Ergebnisseite", results_body)
            self.assertIn("autorun.bat", results_body)
            self.assertIn("dropper.exe", results_body)
            detail_body = detail_page_path.read_text(encoding="utf-8")
            self.assertIn("system_guard_results.html", detail_body)
            self.assertIn("system_guard_report.html", detail_body)
            latest_status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertTrue(latest_status["changed"])
            self.assertGreaterEqual(latest_status["scope_count"], 4)
            self.assertEqual(Path(latest_status["results_path"]).name, "system_guard_results.html")

    def test_system_guard_bootstrap_artifacts_exist_before_first_scan(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_system_guard_helper.py"
        helper = runpy.run_path(str(helper_path))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            state_dir = project / ".nova_system_guard"
            state_dir.mkdir(parents=True, exist_ok=True)
            scopes = [
                {
                    "name": "custom_1",
                    "title": "Custom Path 1",
                    "path": project,
                    "category": "custom",
                    "priority": "high",
                    "weight": 42,
                    "recurse": True,
                    "extensions": None,
                }
            ]
            runtime = {
                "watch_mode": "watchdog",
                "watch_requested": "auto",
                "watch_reason": "",
                "watchdog_available": True,
                "scope_titles": [scope["title"] for scope in scopes],
            }

            helper["write_bootstrap_artifacts"](project, state_dir, scopes, runtime)

            report_path = state_dir / "system_guard_report.html"
            results_path = state_dir / "system_guard_results.html"
            status_path = state_dir / "latest_status.json"
            analysis_path = state_dir / "system_guard_analysis.json"

            self.assertTrue(report_path.is_file())
            self.assertTrue(results_path.is_file())
            self.assertTrue(status_path.is_file())
            self.assertTrue(analysis_path.is_file())

            html_body = report_path.read_text(encoding="utf-8")
            results_body = results_path.read_text(encoding="utf-8")
            self.assertIn("Initialer Sicherheits-Scan läuft", html_body)
            self.assertIn("Custom Path 1", html_body)
            self.assertIn("Letzte abgeschlossene Ergebnisseite", html_body)
            self.assertIn("Noch keine abgeschlossene Ergebnisseite vorhanden", results_body)

            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_payload["phase"], "initializing")
            self.assertEqual(status_payload["scope_count"], 1)
            self.assertEqual(status_payload["status_line"], "Initialer Sicherheits-Scan läuft.")
            self.assertEqual(Path(status_payload["results_path"]).name, "system_guard_results.html")

    def test_system_guard_bootstrap_keeps_existing_results_page(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_system_guard_helper.py"
        helper = runpy.run_path(str(helper_path))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            state_dir = project / ".nova_system_guard"
            state_dir.mkdir(parents=True, exist_ok=True)
            scopes = [
                {
                    "name": "custom_1",
                    "title": "Custom Path 1",
                    "path": project,
                    "category": "custom",
                    "priority": "high",
                    "weight": 42,
                    "recurse": True,
                    "extensions": None,
                }
            ]
            runtime = {
                "watch_mode": "poll",
                "watch_requested": "auto",
                "watch_reason": "",
                "watchdog_available": False,
                "scope_titles": [scope["title"] for scope in scopes],
            }
            results_path = state_dir / "system_guard_results.html"
            results_path.write_text("stable-results-marker", encoding="utf-8")

            helper["write_bootstrap_artifacts"](project, state_dir, scopes, runtime, phase="scanning")

            self.assertEqual(results_path.read_text(encoding="utf-8"), "stable-results-marker")

    def test_system_guard_poll_probe_only_requests_rescan_on_real_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_system_guard_helper.py"
        helper = runpy.run_path(str(helper_path))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            startup_dir = project / "startup"
            startup_dir.mkdir(parents=True, exist_ok=True)
            watched = startup_dir / "autorun.bat"
            watched.write_text("@echo off\necho baseline\n", encoding="utf-8")
            scopes = [
                {
                    "name": "custom_startup",
                    "title": "Custom Startup Path",
                    "path": startup_dir,
                    "category": "persistence",
                    "priority": "critical",
                    "weight": 90,
                    "recurse": True,
                    "extensions": None,
                }
            ]

            snapshot = helper["scan_targets"](scopes)
            self.assertFalse(helper["poll_requires_rescan"](scopes, snapshot))

            time.sleep(0.02)
            watched.write_text("@echo off\necho changed\n", encoding="utf-8")
            self.assertTrue(helper["poll_requires_rescan"](scopes, snapshot))

    def test_system_guard_main_reuses_existing_snapshot_without_bootstrap_rescan(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_system_guard_helper.py"
        helper = runpy.run_path(str(helper_path))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            startup_dir = project / "startup"
            startup_dir.mkdir(parents=True, exist_ok=True)
            watched = startup_dir / "autorun.bat"
            watched.write_text("@echo off\necho baseline\n", encoding="utf-8")
            state_dir = project / ".nova_system_guard"
            state_dir.mkdir(parents=True, exist_ok=True)

            with patch.dict(
                os.environ,
                {
                    "NOVA_SYSTEM_GUARD_ROOT": str(project),
                    "NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS": "0",
                    "NOVA_SYSTEM_GUARD_INCLUDE_WINDOWS_INVENTORY": "0",
                    "NOVA_SYSTEM_GUARD_INCLUDE_PROJECT": "off",
                    "NOVA_SYSTEM_GUARD_PATHS": str(startup_dir),
                    "NOVA_SYSTEM_GUARD_ONESHOT": "1",
                    "NOVA_SYSTEM_GUARD_OPEN": "0",
                },
                clear=False,
            ):
                scopes = helper["resolve_scope_specs"](project)
                snapshot = helper["scan_targets"](scopes)
                event = {
                    "id": "baseline-1",
                    "timestamp": snapshot["generated_at"],
                    "kind": "baseline",
                    "summary": "Erster Sicherheitsstand wurde aufgenommen.",
                    "created": [],
                    "modified": [],
                    "deleted": [],
                    "actions": [],
                    "review": {
                        "severity": "low",
                        "score": 5,
                        "headline": "Baseline",
                        "summary": "Keine Auffaelligkeiten.",
                        "findings": [],
                        "recommendations": [],
                    },
                }
                analysis = helper["build_analysis"]([event], snapshot)
                (state_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
                (state_dir / "history.json").write_text(
                    json.dumps({"generated_at": snapshot["generated_at"], "events": [event]}, ensure_ascii=False),
                    encoding="utf-8",
                )
                (state_dir / "system_guard_analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
                (state_dir / "latest_status.json").write_text(
                    json.dumps(
                        {
                            "generated_at": snapshot["generated_at"],
                            "changed": False,
                            "event": event,
                            "review": event["review"],
                            "runtime": {"watch_mode": "poll"},
                            "tracked_files": snapshot["file_count"],
                            "scope_count": len(scopes),
                            "report_path": str(state_dir / "system_guard_report.html"),
                            "results_path": str(state_dir / "system_guard_results.html"),
                            "analysis_path": str(state_dir / "system_guard_analysis.json"),
                            "actions": [],
                            "status_line": "Baseline gespeichert.",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                payload = helper["main"]()

            self.assertFalse(payload["changed"])
            self.assertEqual(payload["phase"], "idle")
            self.assertIn("Keine neuen Aenderungen erkannt", payload["status_line"])
            live_body = (state_dir / "system_guard_report.html").read_text(encoding="utf-8")
            self.assertIn("Bestehende Baseline wiederverwendet", live_body)
            self.assertIn("Letzter Vollscan", live_body)
            self.assertIn("Keine neuen Aenderungen seitdem erkannt", live_body)
            self.assertIn("Keine neuen Aenderungen erkannt", live_body)
            self.assertNotIn("Initialer Sicherheits-Scan läuft", live_body)

    def test_system_guard_bootstrap_artifacts_include_live_progress(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_system_guard_helper.py"
        helper = runpy.run_path(str(helper_path))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            state_dir = project / ".nova_system_guard"
            state_dir.mkdir(parents=True, exist_ok=True)
            scopes = [
                {
                    "name": "downloads_watch",
                    "title": "Downloads Watch",
                    "path": project / "downloads",
                    "category": "downloads",
                    "priority": "high",
                    "weight": 75,
                    "recurse": True,
                    "extensions": None,
                }
            ]
            runtime = {
                "watch_mode": "poll",
                "watch_requested": "auto",
                "watch_reason": "",
                "watchdog_available": False,
                "scope_titles": [scope["title"] for scope in scopes],
            }
            progress = {
                "phase": "scanning",
                "current_scope_name": "downloads_watch",
                "current_scope_title": "Downloads Watch",
                "current_scope_path": str(project / "downloads"),
                "last_path": str(project / "downloads" / "payload.exe"),
                "processed_files": 17,
                "processed_scope_files": 5,
                "scanned_scopes": 0,
                "total_scopes": 1,
            }

            helper["write_bootstrap_artifacts"](
                project,
                state_dir,
                scopes,
                runtime,
                progress=progress,
                phase="scanning",
            )

            html_body = (state_dir / "system_guard_report.html").read_text(encoding="utf-8")
            self.assertIn("Downloads Watch", html_body)
            self.assertIn("payload.exe", html_body)
            self.assertIn("17", html_body)
            self.assertIn("5", html_body)
            self.assertIn("Letzte abgeschlossene Ergebnisseite", html_body)

            status_payload = json.loads((state_dir / "latest_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status_payload["phase"], "scanning")
            self.assertEqual(status_payload["progress"]["current_scope_title"], "Downloads Watch")
            self.assertEqual(status_payload["progress"]["processed_files"], 17)
            self.assertIn("payload.exe", status_payload["status_line"])

    def test_ns_run_system_guard_supports_signature_inventory_and_quarantine(self) -> None:
        root = Path(__file__).resolve().parents[1]
        helper_path = root / "examples" / "nova_system_guard_helper.py"
        generator_path = root / "scripts" / "generate_system_guard_ns.py"
        generator = runpy.run_path(str(generator_path))
        ns_text = generator["build_ns_text"](helper_path.read_text(encoding="utf-8"))
        original_run = subprocess.run

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            startup_dir = project / "startup"
            temp_dir = project / "temp"
            startup_dir.mkdir(parents=True, exist_ok=True)
            temp_dir.mkdir(parents=True, exist_ok=True)
            script_file = project / "nova_system_guard.ns"
            startup_file = startup_dir / "autorun.bat"
            startup_file.write_text("@echo off\necho baseline\n", encoding="utf-8")
            script_file.write_text(ns_text, encoding="utf-8")
            phase = {"value": "baseline"}

            def fake_subprocess_run(command: list[str], **kwargs: object) -> SimpleNamespace:
                if command and str(command[0]).lower() == "powershell":
                    script_text = str(command[-1])
                    if "Get-ScheduledTask" in script_text:
                        payload = (
                            []
                            if phase["value"] == "baseline"
                            else [
                                {
                                    "TaskName": "UpdaterHelper",
                                    "TaskPath": "\\Custom\\",
                                    "State": "Ready",
                                    "Author": "Unknown",
                                    "Actions": "powershell.exe -ExecutionPolicy Bypass -File C:\\Temp\\stage.ps1",
                                    "Principal": "SYSTEM",
                                }
                            ]
                        )
                        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
                    if "CurrentVersion\\Run" in script_text:
                        payload = (
                            []
                            if phase["value"] == "baseline"
                            else [
                                {
                                    "KeyPath": "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                    "Name": "UpdaterHelper",
                                    "Command": "C:\\Temp\\dropper.exe /background",
                                }
                            ]
                        )
                        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
                    if "Get-AuthenticodeSignature" in script_text:
                        status_payload = {
                            "Status": "NotSigned",
                            "StatusMessage": "File is not signed.",
                            "Publisher": "",
                            "Thumbprint": "",
                        }
                        return SimpleNamespace(returncode=0, stdout=json.dumps(status_payload), stderr="")
                return original_run(command, **kwargs)

            with patch.dict(
                os.environ,
                {
                    "NOVA_SYSTEM_GUARD_INCLUDE_DEFAULTS": "0",
                    "NOVA_SYSTEM_GUARD_INCLUDE_PROJECT": "off",
                    "NOVA_SYSTEM_GUARD_PATHS": f"{startup_dir};{temp_dir}",
                    "NOVA_SYSTEM_GUARD_ONESHOT": "1",
                    "NOVA_SYSTEM_GUARD_OPEN": "0",
                    "NOVA_SYSTEM_GUARD_ACTION": "high",
                },
                clear=False,
            ):
                with patch("subprocess.run", side_effect=fake_subprocess_run):
                    self.shell.route(f"cd {project}")
                    first = self.shell.route(f"ns.run {script_file}")
                    self.assertIsNone(first.error)

                    phase["value"] = "change"
                    startup_file.write_text("@echo off\npowershell.exe -ExecutionPolicy Bypass -File C:\\Temp\\stage.ps1\n", encoding="utf-8")
                    dropper = temp_dir / "dropper.exe"
                    dropper.write_bytes(b"MZ\x90\x00payload")
                    second = self.shell.route(f"ns.run {script_file}")
                    self.assertIsNone(second.error)

            guard_dir = project / ".nova_system_guard"
            history_payload = json.loads((guard_dir / "history.json").read_text(encoding="utf-8"))
            change_event = history_payload["events"][-1]
            created_kinds = {item["kind"] for item in change_event["created"]}
            if os.name == "nt":
                self.assertIn("scheduled_task", created_kinds)
                self.assertIn("run_key", created_kinds)
            file_created = next(item for item in change_event["created"] if item["kind"] == "executable")
            if os.name == "nt":
                self.assertEqual(file_created["signature_status"], "NotSigned")
            else:
                self.assertEqual(file_created["signature_status"], "unavailable")
            self.assertIn("quarantine", file_created)
            self.assertTrue(file_created["quarantine"]["success"])
            self.assertFalse((temp_dir / "dropper.exe").exists())
            quarantine_target = Path(file_created["quarantine"]["target_path"])
            self.assertTrue(quarantine_target.is_file())
            latest_status = json.loads((guard_dir / "latest_status.json").read_text(encoding="utf-8"))
            self.assertTrue(any(action["type"] == "quarantine" for action in latest_status["actions"]))
            html_body = (guard_dir / "system_guard_report.html").read_text(encoding="utf-8")
            self.assertIn("Signatur- und Publisher-Pruefung", html_body)
            self.assertIn("Scheduled Tasks", html_body)
            self.assertIn("Registry Run Keys", html_body)
            self.assertIn("quarantine", html_body)

    def test_run_morning_briefing_can_use_custom_reference_files_without_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sample_news = (root / "sample_news.json").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp).resolve()
            custom_reference = report_dir / "market_strategy.md"
            custom_reference.write_text("# Strategy\nFocus on edge inference.\n", encoding="utf-8")
            self.shell.route(f"cd {root}")
            with patch.dict(
                os.environ,
                {
                    "INDUSTRY_SCAN_FILE": str(sample_news),
                    "NOVA_RESONANCE_THRESHOLD": "0.35",
                },
                clear=False,
            ):
                run = self.shell._run_morning_briefing_job(
                    topic="AI infrastructure agent runtime",
                    report_dir_text=str(report_dir),
                    reference_files_text=str(custom_reference),
                    include_default_context=False,
                )
            reference_payload = run.get("reference_payload", {})
            embedded = reference_payload.get("embedded", [])
            self.assertEqual(len(embedded), 1)
            self.assertEqual(embedded[0]["path"], str(custom_reference))
            self.assertFalse(reference_payload.get("include_default_context"))
            listing = self.shell.route("memory list --namespace morning_briefing --project rss_monitoring")
            self.assertIsNone(listing.error)
            memory_payload = json.loads(listing.output)
            paths = {str(item.get("metadata", {}).get("source_file", "")) for item in memory_payload}
            self.assertIn(str(custom_reference), paths)


    def test_mesh_add_and_list(self) -> None:
        add_result = self.shell.route("mesh add http://127.0.0.1:9999 gpu,cpu")
        self.assertIsNone(add_result.error)
        list_result = self.shell.route("mesh list")
        self.assertIsNone(list_result.error)
        payload = json.loads(list_result.output)
        self.assertEqual(payload[0]["url"], "http://127.0.0.1:9999")
        self.assertIn("gpu", payload[0]["caps"])

    def test_mesh_run_reports_missing_capability(self) -> None:
        result = self.shell.route("mesh run gpu py 1 + 1")
        self.assertIsNotNone(result.error)
        self.assertIn("no worker", result.error)

    def test_flow_state_set_get_and_count_last(self) -> None:
        set_result = self.shell.route("flow state set mode active")
        self.assertIsNone(set_result.error)
        get_result = self.shell.route("flow state get mode")
        self.assertEqual(get_result.output.strip(), "active")

        self.shell.route("py 1 + 1")
        count_result = self.shell.route("flow count-last 5 py*")
        self.assertIsNone(count_result.error)
        self.assertGreaterEqual(int(count_result.output.strip()), 1)

    def test_studio_completions_and_graph(self) -> None:
        comp_result = self.shell.route("studio completions ns")
        self.assertIsNone(comp_result.error)
        items = json.loads(comp_result.output)
        self.assertIn("ns.exec", items)

        self.shell.route("py 1 + 1 | py _ + 1")
        graph_result = self.shell.route("studio graph")
        self.assertIsNone(graph_result.error)
        graph = json.loads(graph_result.output)
        self.assertTrue(graph)
        self.assertEqual(graph[0]["name"], "py_chain")

    def test_fabric_put_arrow_missing_dependency_or_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "items.csv"
            csv_file.write_text("name,value\na,1\n", encoding="utf-8")
            result = self.shell.route(f"fabric put-arrow {csv_file}")
            if result.error is None:
                handle = result.output.strip()
                self.assertTrue(handle)
            else:
                self.assertIn("pyarrow", result.error)


    def test_jit_wasm_compiles_or_reports_missing_runtime(self) -> None:
        result = self.shell.route("jit_wasm 1 + 2 * 3")
        if result.error is None:
            self.assertEqual(float(result.output.strip()), 7.0)
            self.assertIn("wat", result.data)
        else:
            self.assertIn("wasmtime", result.error)

    def test_sync_crdt_counter_and_map(self) -> None:
        inc = self.shell.route("sync inc global_counter 2")
        self.assertIsNone(inc.error)
        got = self.shell.route("sync get global_counter")
        self.assertEqual(got.output.strip(), "2")

        set_result = self.shell.route("sync set feature_x enabled")
        self.assertIsNone(set_result.error)
        key_result = self.shell.route("sync get-key feature_x")
        self.assertEqual(key_result.output.strip(), "enabled")

        export_result = self.shell.route("sync export")
        self.assertIsNone(export_result.error)
        payload = json.loads(export_result.output)
        self.assertIn("counters", payload)

    def test_lens_snapshots_list_and_show(self) -> None:
        self.shell.route("py 2 + 2")
        last = self.shell.route("lens last")
        self.assertIsNone(last.error)
        snapshot = json.loads(last.output)
        self.assertIn("id", snapshot)

        show = self.shell.route(f"lens show {snapshot['id']}")
        self.assertIsNone(show.error)
        detail = json.loads(show.output)
        self.assertEqual(detail["id"], snapshot["id"])

    def test_fabric_remote_commands_validate_errors(self) -> None:
        put = self.shell.route("fabric remote-put http://127.0.0.1:1 hello")
        self.assertIsNotNone(put.error)
        self.assertIn("remote-put", put.error)

    def test_ai_env_reload_and_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("OPENAI_API_KEY=test-openai\nLM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1\n", encoding="utf-8")
            self.shell.cwd = Path(tmp)
            self.shell.ai_runtime.cwd = Path(tmp)
            reload_result = self.shell.route("ai env reload")
            self.assertIsNone(reload_result.error)
            payload = json.loads(reload_result.output)
            loaded = {str(Path(item).resolve(strict=False)).casefold() for item in payload["loaded_env_files"]}
            self.assertIn(str(env_file.resolve(strict=False)).casefold(), loaded)

            providers = self.shell.route("ai providers")
            self.assertIsNone(providers.error)
            rows = json.loads(providers.output)
            openai = next(item for item in rows if item["provider"] == "openai")
            lmstudio = next(item for item in rows if item["provider"] == "lmstudio")
            self.assertTrue(openai["configured"])
            self.assertTrue(lmstudio["configured"])

    def test_ai_models_use_and_prompt_with_lmstudio(self) -> None:
        observed_timeouts: list[int] = []

        def fake_urlopen(request: object, timeout: int = 0) -> FakeHTTPResponse:
            observed_timeouts.append(int(timeout))
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if url.endswith("/models"):
                return FakeHTTPResponse({"data": [{"id": "local-model"}, {"id": "fallback-model"}]})
            if url.endswith("/chat/completions"):
                return FakeHTTPResponse({"choices": [{"message": {"content": "hello from lmstudio"}}]})
            raise AssertionError(f"unexpected url: {url}")

        with patch("nova_shell.urllib.request.urlopen", side_effect=fake_urlopen):
            models = self.shell.route("ai models lmstudio")
            self.assertIsNone(models.error)
            models_payload = json.loads(models.output)
            self.assertIn("local-model", models_payload["models"])

            selected = self.shell.route("ai use lmstudio local-model")
            self.assertIsNone(selected.error)
            selected_payload = json.loads(selected.output)
            self.assertEqual(selected_payload["provider"], "lmstudio")
            self.assertEqual(selected_payload["model"], "local-model")

            prompt = self.shell.route('ai prompt "say hello"')
            self.assertIsNone(prompt.error)
            self.assertIn("hello from lmstudio", prompt.output)

        self.assertGreaterEqual(max(observed_timeouts), 180)

    def test_ai_prompt_without_provider_uses_heuristic_plan(self) -> None:
        with patch.object(self.shell.ai_runtime, "get_active_provider", return_value=""):
            self.shell.ai_runtime.active_provider = ""
            self.shell.ai_runtime.active_model = ""
            result = self.shell.route('ai "calculate csv average"')
        self.assertIsNone(result.error)
        self.assertIn("tool.call csv_load", result.output)

    def test_memory_embed_and_search(self) -> None:
        first = self.shell.route('memory embed --id groceries "Brot Käse Apfel Preise Lebensmittel"')
        self.assertIsNone(first.error)

        second = self.shell.route('memory embed --id infra "GPU Mesh Worker Scheduler Cluster"')
        self.assertIsNone(second.error)

        search = self.shell.route('memory search "Käse Lebensmittel"')
        self.assertIsNone(search.error)
        payload = json.loads(search.output)
        self.assertGreaterEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], "groceries")

    def test_memory_namespace_project_scope_persists_across_shells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_home = Path(tmp)
            first_shell: NovaShell | None = None
            second_shell: NovaShell | None = None
            with patch("nova_shell.Path.home", return_value=temp_home):
                try:
                    first_shell = NovaShell()
                    self.assertIsNone(first_shell.route("memory namespace finance").error)
                    self.assertIsNone(first_shell.route("memory project q1").error)
                    self.assertIsNone(first_shell.route('memory embed --id sales "Revenue price gross margin"').error)
                    self.assertIsNone(first_shell.route("memory project q2").error)
                    self.assertIsNone(first_shell.route('memory embed --id forecast "Forecast pipeline bookings"').error)

                    status = first_shell.route("memory status")
                    self.assertIsNone(status.error)
                    status_payload = json.loads(status.output)
                    self.assertEqual(status_payload["namespace"], "finance")
                    self.assertEqual(status_payload["project"], "q2")
                    self.assertEqual(status_payload["count"], 1)
                    self.assertEqual(status_payload["total_count"], 2)

                    scoped = first_shell.route("memory list")
                    self.assertIsNone(scoped.error)
                    self.assertEqual([row["id"] for row in json.loads(scoped.output)], ["forecast"])

                    all_rows = first_shell.route("memory list --all")
                    self.assertIsNone(all_rows.error)
                    self.assertEqual({row["id"] for row in json.loads(all_rows.output)}, {"sales", "forecast"})
                finally:
                    if first_shell is not None:
                        first_shell._close_loop()

                try:
                    second_shell = NovaShell()
                    self.assertIsNone(second_shell.route("memory namespace finance").error)
                    self.assertIsNone(second_shell.route("memory project q1").error)
                    search = second_shell.route('memory search "revenue price"')
                    self.assertIsNone(search.error)
                    payload = json.loads(search.output)
                    self.assertEqual(payload[0]["id"], "sales")
                    self.assertEqual(payload[0]["namespace"], "finance")
                    self.assertEqual(payload[0]["project"], "q1")
                finally:
                    if second_shell is not None:
                        second_shell._close_loop()

    def test_atheria_status_command_reports_payload(self) -> None:
        payload = {"available": True, "trained_records": 3, "source_dir": "D:/Nova-shell/Atheria"}
        with patch.object(self.shell.atheria, "status_payload", return_value=payload):
            result = self.shell.route("atheria status")
        self.assertIsNone(result.error)
        self.assertEqual(json.loads(result.output), payload)

    def test_atheria_train_qa_and_chat(self) -> None:
        with patch.object(self.shell.atheria, "train_qa", return_value=1) as train_mock, patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(output="Atheria reply\n", data={"text": "Atheria reply"}, data_type=PipelineType.OBJECT),
        ) as complete_mock:
            trained = self.shell.route('atheria train qa --question "What is Nova-shell?" --answer "A unified runtime." --category product')
            chatted = self.shell.route('atheria chat "What is Nova-shell?"')

        self.assertIsNone(trained.error)
        self.assertEqual(json.loads(trained.output)["inserted"], 1)
        train_mock.assert_called_once_with(question="What is Nova-shell?", answer="A unified runtime.", category="product")

        self.assertIsNone(chatted.error)
        self.assertEqual(chatted.output.strip(), "Atheria reply")
        self.assertEqual(complete_mock.call_args.kwargs["provider"], "atheria")
        self.assertEqual(complete_mock.call_args.kwargs["model"], "atheria-core")

    def test_atheria_train_memory_uses_memory_entry(self) -> None:
        embedded = self.shell.route('memory embed --id transcript "Segment one\n\nSegment two"')
        self.assertIsNone(embedded.error)

        with patch.object(self.shell.atheria, "train_rows", return_value=2) as train_mock:
            result = self.shell.route("atheria train memory transcript --category video")

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["mode"], "memory")
        self.assertEqual(payload["memory_id"], "transcript")
        self.assertEqual(payload["inserted"], 2)
        rows = train_mock.call_args.args[0]
        self.assertEqual(rows[0][0], "transcript segment 1")
        self.assertEqual(rows[0][1], "video")
        self.assertEqual(rows[0][2], "Segment one")
        self.assertEqual(rows[1][2], "Segment two")

    def test_atheria_runtime_persists_hyperbolic_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("nova_shell.Path.home", return_value=tmp_path):
                runtime = NovaAtheriaRuntime({}, tmp_path)
                inserted = runtime.train_rows([("What is Nova-shell?", "product", "A unified runtime.")])

                self.assertEqual(inserted, 1)
                payload = json.loads(runtime.training_store_path.read_text(encoding="utf-8"))
                self.assertEqual(payload[0]["embedding_space"], "poincare")
                self.assertEqual(payload[0]["embedding_model"], "atheria-poincare-memory-v1")
                self.assertEqual(len(payload[0]["embedding"]), payload[0]["embedding_dims"])
                self.assertTrue(any(abs(float(value)) > 0.0 for value in payload[0]["embedding"]))

    def test_atheria_runtime_migrates_legacy_rows_to_hyperbolic_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("nova_shell.Path.home", return_value=tmp_path):
                store = tmp_path / ".nova_shell_memory" / "atheria_training.json"
                store.parent.mkdir(parents=True, exist_ok=True)
                store.write_text(
                    json.dumps(
                        [
                            {
                                "question": "What is Atheria?",
                                "category": "identity",
                                "answer": "A local trainable intelligence.",
                            }
                        ],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                runtime = NovaAtheriaRuntime({}, tmp_path)

                self.assertEqual(runtime._loaded_training[0]["embedding_space"], "poincare")
                persisted = json.loads(store.read_text(encoding="utf-8"))
                self.assertIn("embedding", persisted[0])
                self.assertEqual(persisted[0]["embedding_model"], "atheria-poincare-memory-v1")

    def test_atheria_runtime_search_uses_poincare_hyperbolic_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("nova_shell.Path.home", return_value=tmp_path):
                runtime = NovaAtheriaRuntime({}, tmp_path)
                runtime.train_rows(
                    [
                        ("average price in items csv", "analysis", "The average price is 2.6."),
                        ("weather in berlin", "weather", "The forecast is sunny."),
                    ]
                )

                results = runtime.search_training("calculate average price in items.csv")

                self.assertTrue(results)
                self.assertEqual(results[0]["category"], "analysis")
                self.assertEqual(results[0]["retrieval_mode"], "poincare_hyperbolic")
                self.assertIn("hyperbolic_similarity", results[0])
                self.assertIn("distance", results[0])

    def test_atheria_runtime_evolution_plan_and_apply_persist_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch("nova_shell.Path.home", return_value=tmp_path):
                runtime = NovaAtheriaRuntime({}, tmp_path)
                report = {
                    "summary": "Edge AI and local inference demand rise while GPU supply chain pressure grows.",
                    "metadata": {
                        "forecast_direction": "emerging_uptrend",
                        "forecast_score": 0.84,
                        "confidence": 0.71,
                        "items": [
                            {"title": "Edge AI devices expand"},
                            {"title": "GPU supply chain risk increases"},
                            {"title": "Local inference adoption rises"},
                        ],
                    },
                    "features": {
                        "signal_strength": 0.81,
                        "resource_pressure": 0.77,
                        "entropic_index": 0.42,
                        "queue_depth": 0.61,
                        "anomaly_score": 0.22,
                    },
                }

                plan = runtime.plan_evolution(report, source_label="unit-test")
                self.assertEqual(plan["kind"], "atheria_evolution_plan")
                self.assertTrue(plan["focus"])
                self.assertIn("reproduction_quality", plan["proposed_state"])

                applied = runtime.apply_evolution(plan, reason="unit-test")
                self.assertEqual(applied["mode"], "apply")
                self.assertTrue(runtime.evolution_state_path.exists())

                persisted = json.loads(runtime.evolution_state_path.read_text(encoding="utf-8"))
                self.assertIn("active_policy", persisted)
                self.assertGreater(float(persisted["reproduction_quality"]), 0.0)
                self.assertTrue(persisted["history"])

    def test_ai_use_atheria_and_prompt_routes_to_atheria_runtime(self) -> None:
        with patch.object(self.shell.atheria, "is_available", return_value=True), patch.object(
            self.shell.atheria,
            "complete_prompt",
            return_value={
                "provider": "atheria",
                "model": "atheria-core",
                "text": "Atheria knows Nova-shell",
                "retrieved": [],
                "field_result": {},
                "dashboard": {"phase": "focused"},
            },
        ) as complete_mock:
            selected = self.shell.route("ai use atheria atheria-core")
            prompted = self.shell.route('ai prompt "what is nova-shell?"')

        self.assertIsNone(selected.error)
        self.assertEqual(json.loads(selected.output)["provider"], "atheria")
        self.assertIsNone(prompted.error)
        self.assertEqual(prompted.output.strip(), "Atheria knows Nova-shell")
        complete_mock.assert_called_once()
        self.assertEqual(complete_mock.call_args.args[0], "what is nova-shell?")

    def test_atheria_als_cycle_persists_chronik_lens_and_voice(self) -> None:
        quiet_rows = [
            {
                "title": "Runtime note",
                "summary": "agent workflow release",
                "source": "feed-a",
                "url": "https://quiet/a",
            }
        ]
        hot_rows = [
            {
                "title": "AI data center boom",
                "summary": "gpu cluster power cooling capacity expansion for agent runtime inference",
                "source": "feed-a",
                "url": "https://hot/1",
            },
            {
                "title": "Inference bottleneck risk",
                "summary": "latency deployment outage risk and runtime orchestration pressure increase",
                "source": "feed-b",
                "url": "https://hot/2",
            },
            {
                "title": "Research benchmark surge",
                "summary": "training inference reasoning paper and model benchmark acceleration",
                "source": "feed-c",
                "url": "https://hot/3",
            },
            {
                "title": "Infrastructure investment spike",
                "summary": "market capex funding data center rack cooling and chip capacity investment",
                "source": "feed-d",
                "url": "https://hot/4",
            },
        ]

        class DummyLens:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def record(self, stage: str, result: CommandResult, trace_id: str, data_preview: str) -> str:
                self.calls.append((stage, result.output))
                return "alssnap123"

            def list(self, limit: int = 10) -> list[dict[str, object]]:
                return [{"id": "alssnap123", "stage": "atheria.als.cycle"}]

        self.shell.als.lens_store = DummyLens()
        with patch.object(self.shell.atheria, "train_rows", return_value=1), patch.object(
            self.shell.federated, "publish_update", return_value={"update_id": "fed123"}
        ):
            first = self.shell.als.run_cycle(rows=quiet_rows)
            second = self.shell.als.run_cycle(rows=hot_rows)

        self.assertFalse(first["triggered"])
        self.assertTrue(second["triggered"])
        self.assertEqual(second["lens_snapshot_id"], "alssnap123")
        self.assertIn("speech_act", second)
        self.assertEqual(second["speech_act"]["mode"], "alert")
        self.assertTrue(self.shell.als.audit_log_path.exists())
        self.assertTrue(self.shell.als.chronik_html_path.exists())
        self.assertTrue(self.shell.als.resonance_path.exists())
        self.assertTrue((self.shell.als.voice_runtime.storage_dir / "latest_speech_act.json").exists())
        self.assertTrue((self.shell.als.voice_runtime.storage_dir / "latest_utterance.txt").exists())
        self.assertTrue((self.shell.als.voice_runtime.storage_dir / "latest_utterance.ssml").exists())
        self.assertIn(
            second["speech_act"]["utterance_text"],
            (self.shell.als.voice_runtime.storage_dir / "latest_utterance.txt").read_text(encoding="utf-8"),
        )

    def test_atheria_als_cycle_does_not_repeat_anomaly_trigger_without_new_signal(self) -> None:
        quiet_rows = [
            {
                "title": "Runtime note",
                "summary": "agent workflow release",
                "source": "feed-a",
                "url": "https://quiet/a",
            }
        ]
        hot_rows = [
            {
                "title": "AI data center boom",
                "summary": "gpu cluster power cooling capacity expansion for agent runtime inference",
                "source": "feed-a",
                "url": "https://hot/1",
            },
            {
                "title": "Inference bottleneck risk",
                "summary": "latency deployment outage risk and runtime orchestration pressure increase",
                "source": "feed-b",
                "url": "https://hot/2",
            },
            {
                "title": "Research benchmark surge",
                "summary": "training inference reasoning paper and model benchmark acceleration",
                "source": "feed-c",
                "url": "https://hot/3",
            },
            {
                "title": "Infrastructure investment spike",
                "summary": "market capex funding data center rack cooling and chip capacity investment",
                "source": "feed-d",
                "url": "https://hot/4",
            },
        ]

        self.shell.als.run_cycle(rows=quiet_rows)
        first_hot = self.shell.als.run_cycle(rows=hot_rows)
        repeated_hot = self.shell.als.run_cycle(rows=hot_rows)

        audit_lines = [line for line in self.shell.als.audit_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(first_hot["triggered"])
        self.assertEqual(first_hot["trigger_reason"], "anomaly_score")
        self.assertFalse(repeated_hot["triggered"])
        self.assertFalse(repeated_hot["fresh_signal"])
        self.assertIn("ohne neue Eingangssignale", repeated_hot["summary"])
        self.assertEqual(len(audit_lines), 2)
        self.assertIn('"reason": "market_anomaly::anomaly_score"', audit_lines[-1])

    def test_atheria_als_chronik_explains_trigger_without_generation_jargon(self) -> None:
        self.shell.als.configure({"topic": "AI infrastructure agent runtime"})
        quiet_rows = [
            {
                "title": "Runtime note",
                "summary": "agent workflow release",
                "source": "feed-a",
                "url": "https://quiet/a",
                "sensor": "rss",
            }
        ]
        hot_rows = [
            {
                "title": "AI data center boom",
                "summary": "gpu cluster power cooling capacity expansion for agent runtime inference",
                "source": "feed-a",
                "url": "https://hot/1",
                "sensor": "rss",
            },
            {
                "title": "Inference bottleneck risk",
                "summary": "latency deployment outage risk and runtime orchestration pressure increase",
                "source": "web_search:duckduckgo_html",
                "url": "https://hot/2",
                "sensor": "web_search",
            },
            {
                "title": "Research benchmark surge",
                "summary": "training inference reasoning paper and model benchmark acceleration",
                "source": "feed-c",
                "url": "https://hot/3",
                "sensor": "rss",
            },
        ]

        self.shell.als.run_cycle(rows=quiet_rows)
        self.shell.als.run_cycle(rows=hot_rows)

        html = self.shell.als.chronik_html_path.read_text(encoding="utf-8")
        self.assertIn("ALS loeste einen Trigger im Informationsfeld aus", html)
        self.assertIn("Anomalie-Score", html)
        self.assertIn("Thema: AI infrastructure agent runtime.", html)
        self.assertIn("Ausloesende Hinweise:", html)
        self.assertIn("Inference bottleneck risk", html)
        self.assertIn("Atheria formulierte:", html)
        self.assertIn("Atheria erkennt eine beschleunigte Resonanzverschiebung im Informationsfeld.", html)
        self.assertNotIn("unbenanntes Offspring", html)
        self.assertNotIn("Eine schwere Marktanomalie loeste eine neue Generation aus", html)

    def test_atheria_als_cycle_can_interpret_output_with_lmstudio_and_persist_to_chronik(self) -> None:
        configure = self.shell.route(
            'atheria als configure --topic "AI infrastructure agent runtime" --analysis on --analysis-provider lmstudio --analysis-model local-model'
        )
        self.assertIsNone(configure.error)
        rows = [
            {
                "title": "Runtime security expansion",
                "summary": "secure agent runtime orchestration and infrastructure control are becoming central topics",
                "source": "rss",
                "url": "https://example.com/als/1",
                "sensor": "rss",
            }
        ]
        with patch.object(self.shell.ai_runtime, "is_configured", side_effect=lambda provider: provider == "lmstudio"), patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(
                output='{"statement":"Atheria meldet einen realen Schwerpunkt auf sichere Agent-Runtimes.","meaning":"Das Signal zeigt, dass Laufzeitkontrolle und Absicherung operativ wichtiger werden.","recommendation":"Die wichtigsten Quellen sollten auf technische Anschlussrisiken geprueft werden.","risk_level":"mittel","confidence":0.74}\n',
                data={
                    "text": '{"statement":"Atheria meldet einen realen Schwerpunkt auf sichere Agent-Runtimes.","meaning":"Das Signal zeigt, dass Laufzeitkontrolle und Absicherung operativ wichtiger werden.","recommendation":"Die wichtigsten Quellen sollten auf technische Anschlussrisiken geprueft werden.","risk_level":"mittel","confidence":0.74}',
                    "provider": "lmstudio",
                    "model": "local-model",
                },
                data_type=PipelineType.OBJECT,
            ),
        ):
            result = self.shell.route("atheria als cycle")

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["interpretation"]["provider"], "lmstudio")
        self.assertEqual(payload["interpretation"]["model"], "local-model")
        self.assertIn("sichere Agent-Runtimes", payload["interpretation"]["text"])
        self.assertTrue(self.shell.als.interpretation_path.exists())
        status = self.shell.als.status_payload()
        self.assertEqual(status["interpretation"]["last_analysis"]["provider"], "lmstudio")
        html = self.shell.als.chronik_html_path.read_text(encoding="utf-8")
        self.assertIn("LM-Studio-Einordnung:", html)
        self.assertIn("Atheria meldet einen realen Schwerpunkt auf sichere Agent-Runtimes.", html)

    def test_atheria_als_analysis_commands_expose_status_last_and_tail(self) -> None:
        self.assertIsNone(
            self.shell.route(
                'atheria als configure --topic "AI infrastructure agent runtime" --analysis on --analysis-provider lmstudio --analysis-model local-model'
            ).error
        )
        rows = [
            {
                "title": "Runtime security expansion",
                "summary": "secure agent runtime orchestration and infrastructure control are becoming central topics",
                "source": "rss",
                "url": "https://example.com/als/1",
                "sensor": "rss",
            }
        ]
        with patch.object(self.shell.ai_runtime, "is_configured", side_effect=lambda provider: provider == "lmstudio"), patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(
                output='{"statement":"Atheria meldet einen Schwerpunkt auf Runtime-Sicherheit.","meaning":"Die Lage deutet auf wachsende operative Relevanz.","recommendation":"Quellen und Anschlussrisiken pruefen.","risk_level":"mittel","confidence":0.71}\n',
                data={
                    "text": '{"statement":"Atheria meldet einen Schwerpunkt auf Runtime-Sicherheit.","meaning":"Die Lage deutet auf wachsende operative Relevanz.","recommendation":"Quellen und Anschlussrisiken pruefen.","risk_level":"mittel","confidence":0.71}',
                    "provider": "lmstudio",
                    "model": "local-model",
                },
                data_type=PipelineType.OBJECT,
            ),
        ):
            self.shell.als.run_cycle(rows=rows)

        status = self.shell.route("atheria als analysis status")
        self.assertIsNone(status.error)
        status_payload = json.loads(status.output)
        self.assertTrue(status_payload["enabled"])
        self.assertEqual(status_payload["provider"], "lmstudio")

        last = self.shell.route("atheria als analysis last")
        self.assertIsNone(last.error)
        last_payload = json.loads(last.output)
        self.assertEqual(last_payload["provider"], "lmstudio")
        self.assertIn("Runtime-Sicherheit", last_payload["text"])

        tail = self.shell.route("atheria als analysis tail --limit 1")
        self.assertIsNone(tail.error)
        tail_payload = json.loads(tail.output)
        self.assertEqual(len(tail_payload), 1)
        self.assertEqual(tail_payload[0]["provider"], "lmstudio")

    def test_atheria_als_learning_changes_output_after_feedback_training(self) -> None:
        query = "omega_gpu_sentinel_zt9"

        with patch.object(self.shell.als, "_build_dialog_probe_event", return_value={}):
            before = self.shell.als.ask(query)
            feedback = self.shell.als.feedback(f"Fuer {query} gilt: GPU-Laufzeitdruck ist das zentrale Risiko.")
            after = self.shell.als.ask(query)

        self.assertEqual(feedback["kind"], "feedback")
        self.assertNotEqual(before["answer"], after["answer"])
        self.assertIn(query, after["answer"])
        self.assertIn("GPU-Laufzeitdruck ist das zentrale Risiko.", after["answer"])

    def test_atheria_als_dynamics_do_not_drift_under_repeated_stable_cycles(self) -> None:
        rows = [
            {
                "title": "Runtime note",
                "summary": "agent workflow release",
                "source": "feed-a",
                "url": "https://quiet/a",
            }
        ]

        anomalies: list[float] = []
        temperatures: list[float] = []
        for _index in range(12):
            event = self.shell.als.run_cycle(rows=[dict(item) for item in rows])
            anomalies.append(float(event["metrics"]["anomaly_score"]))
            temperatures.append(float(event["metrics"]["system_temperature"]))

        steady_state_anomalies = anomalies[1:]
        steady_state_temperatures = temperatures[1:]
        mean_temperature = sum(steady_state_temperatures) / max(1, len(steady_state_temperatures))
        variance = sum((value - mean_temperature) ** 2 for value in steady_state_temperatures) / max(1, len(steady_state_temperatures))

        self.assertLess(max(steady_state_anomalies), 0.15)
        self.assertLess(variance, 1e-9)

    def test_atheria_als_focus_remains_stable_for_consistent_signal_field(self) -> None:
        primary_focuses: list[str] = []

        for index in range(12):
            event = self.shell.als.run_cycle(
                rows=[
                    {
                        "title": f"Agent runtime orchestration wave {index}",
                        "summary": "agent runtime workflow orchestrator automation tool graph deployment scale latency server network",
                        "source": f"feed-{index % 3}",
                        "url": f"https://example.com/a/{index}",
                    },
                    {
                        "title": f"Agent tool graph operations note {index}",
                        "summary": "agent runtime automation planner tool graph throughput uptime deployment server region",
                        "source": f"feed-{(index + 1) % 3}",
                        "url": f"https://example.com/b/{index}",
                    },
                ]
            )
            self.assertTrue(event["dominant_topics"])
            primary_focuses.append(str(event["dominant_topics"][0]))

        self.assertEqual(len(set(primary_focuses)), 1)
        self.assertEqual(primary_focuses[0], "agents")

    def test_atheria_als_memory_training_influences_future_answers(self) -> None:
        query = "sigma_memory_lattice"

        before = self.shell.als.ask(query)
        self.shell.memory.embed(
            f"{query} bedeutet: GPU-Orchestrierung hat Vorrang.",
            entry_id=query,
        )
        train = self.shell.route(f"atheria train memory {query} --category system_dynamics")
        after = self.shell.als.ask(query)

        self.assertIsNone(train.error)
        self.assertNotEqual(before["answer"], after["answer"])
        self.assertIn("GPU-Orchestrierung hat Vorrang.", after["answer"])

    def test_atheria_als_ask_routes_through_atheria_and_creates_speech_act(self) -> None:
        class DummyLens:
            def list(self, limit: int = 10) -> list[dict[str, object]]:
                return [{"id": "alssnap123", "stage": "atheria.als.cycle"}]

        self.shell.als.lens_store = DummyLens()
        self.shell.als._append_jsonl(
            self.shell.als.events_path,
            {
                "event_id": "als_event_1",
                "summary": "Atheria erkennt steigende Laufzeitspannung.",
                "metrics": {"signal_strength": 0.82, "system_temperature": 0.77, "anomaly_score": 0.21},
            },
        )
        with patch.object(self.shell.ai_runtime, "is_configured", side_effect=lambda provider: provider == "atheria"), patch.object(
            self.shell.ai_runtime,
            "get_active_model",
            side_effect=lambda provider=None: "atheria-core" if provider == "atheria" else "",
        ), patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(
                output="Atheria answer\n",
                data={"text": "Atheria answer", "provider": "atheria", "model": "atheria-core"},
                data_type=PipelineType.OBJECT,
            ),
        ):
            result = self.shell.route('atheria als ask "What is the current resonance?"')

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["provider"], "atheria")
        self.assertTrue(payload["answer"].startswith("Atheria answer"))
        self.assertIn("Risikoeinordnung:", payload["answer"])
        self.assertEqual(payload["speech_act"]["mode"], "dialog")
        self.assertTrue(self.shell.als.voice_path.exists())

    def test_atheria_als_ask_strips_internal_payload_sections_from_visible_answer(self) -> None:
        self.shell.als._append_jsonl(
            self.shell.als.events_path,
            {
                "event_id": "live_2",
                "summary": "Atheria erkennt eine beschleunigte Resonanzverschiebung im Informationsfeld.",
                "metrics": {"signal_strength": 0.51, "system_temperature": 0.13, "anomaly_score": 1.0},
            },
        )
        noisy_answer = (
            "Atheria erkennt eine beschleunigte Resonanzverschiebung im Informationsfeld. "
            "Fokus: sichere Agent-Runtimes und AI-Infrastruktur.\n"
            "{\"metrics\": {\"signal_strength\": 0.51}}\n\n"
            "Weitere Atheria-Erinnerungen:\n- command_logic: graph aot <pipeline>\n\n"
            "Atheria-Zustand:\n- Resonanz: Analyse, Reaktion\n\n"
            "Systemfokus: Du bist Atheria ALS."
        )
        with patch.object(self.shell.ai_runtime, "is_configured", side_effect=lambda provider: provider == "atheria"), patch.object(
            self.shell.ai_runtime,
            "get_active_model",
            side_effect=lambda provider=None: "atheria-core" if provider == "atheria" else "",
        ), patch.object(
            self.shell.als,
            "_build_dialog_probe_event",
            return_value={},
        ), patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(
                output=noisy_answer,
                data={"text": noisy_answer, "provider": "atheria", "model": "atheria-core"},
                data_type=PipelineType.OBJECT,
            ),
        ):
            result = self.shell.route('atheria als ask "Was ist im Informationsfeld gerade dominant?"')

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertTrue(payload["answer"].startswith("Atheria erkennt eine beschleunigte Resonanzverschiebung im Informationsfeld."))
        self.assertIn("Risikoeinordnung: niedrig", payload["answer"])
        self.assertEqual(payload["speech_act"]["utterance_text"], payload["answer"])
        self.assertNotIn("Weitere Atheria-Erinnerungen", payload["answer"])
        self.assertNotIn("Systemfokus", payload["answer"])
        self.assertNotIn('{"metrics"', payload["answer"])

    def test_atheria_als_ask_exposes_risk_and_source_titles_for_live_evidence(self) -> None:
        state = self.shell.als._load_state()
        state["current_resonance"] = {
            "signal_strength": 0.61,
            "system_temperature": 0.67,
            "anomaly_score": 0.92,
            "confidence": 0.44,
            "structural_tension": 0.28,
            "keyword_groups": {"agents": 0.91, "operations": 0.41, "risk": 0.14},
        }
        self.shell.als._save_state(state)
        self.shell.als._append_jsonl(
            self.shell.als.events_path,
            {
                "event_id": "live_event_1",
                "summary": "Atheria erkennt Agenten- und Sicherheitsdruck.",
                "metrics": dict(state["current_resonance"]),
                "items": [
                    {"title": "Anthropic flagged as national security risk"},
                    {"title": "Secure AI runtime launched for enterprise agents"},
                    {"title": "Quantum cryptography receives Turing Award"},
                ],
            },
        )
        with patch.object(self.shell.ai_runtime, "is_configured", side_effect=lambda provider: provider == "atheria"), patch.object(
            self.shell.ai_runtime,
            "get_active_model",
            side_effect=lambda provider=None: "atheria-core" if provider == "atheria" else "",
        ), patch.object(
            self.shell.als,
            "_build_dialog_probe_event",
            return_value={},
        ), patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(
                output="Atheria erkennt eine dominante Sicherheits- und Runtime-Lage.",
                data={
                    "text": "Atheria erkennt eine dominante Sicherheits- und Runtime-Lage.",
                    "provider": "atheria",
                    "model": "atheria-core",
                },
                data_type=PipelineType.OBJECT,
            ),
        ):
            result = self.shell.route('atheria als ask "Was ist im Informationsfeld gerade dominant?"')

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertIn("Dominante Felder: Agenten und Laufzeit, Betrieb und Skalierung, Risiko und Sicherheit.", payload["answer"])
        self.assertIn("Risikoeinordnung: hoch", payload["answer"])
        self.assertEqual(
            payload["source_titles"],
            [
                "Anthropic flagged as national security risk",
                "Secure AI runtime launched for enterprise agents",
                "Quantum cryptography receives Turing Award",
            ],
        )
        self.assertEqual(payload["risk_assessment"]["level"], "hoch")
        self.assertEqual(payload["dominant_topics"], ["Agenten und Laufzeit", "Betrieb und Skalierung", "Risiko und Sicherheit"])

    def test_atheria_als_ask_prefers_fresh_question_grounded_rss_and_web_evidence(self) -> None:
        self.shell.als._append_jsonl(
            self.shell.als.events_path,
            {
                "event_id": "stale_bio_1",
                "summary": "Atheria beobachtet ein frueheres Forschungsfeld.",
                "metrics": {"signal_strength": 0.55, "system_temperature": 0.57, "anomaly_score": 1.0, "confidence": 0.42},
                "items": [
                    {"title": "Comprehensive evaluation of milk biomarkers as indicators of intramammary infection in dairy goats across lactation"},
                    {"title": "Microglia cause HIV-induced transcriptional and metabolic changes in human neural organoids"},
                ],
            },
        )
        rss_xml = """
        <rss><channel>
          <item>
            <title>How conversational agents shape trust and compliance in users</title>
            <description>Researchers report measurable influence on perception, trust and guided behavior.</description>
            <link>https://example.com/rss/agents-trust</link>
            <pubDate>Thu, 20 Mar 2026 06:00:00 GMT</pubDate>
          </item>
          <item>
            <title>Agent systems can steer attention through adaptive dialogue patterns</title>
            <description>New evidence links agent framing to changes in user judgement.</description>
            <link>https://example.com/rss/agents-attention</link>
            <pubDate>Thu, 20 Mar 2026 06:05:00 GMT</pubDate>
          </item>
        </channel></rss>
        """
        search_html = """
        <html><body>
          <a class="result__a" href="https://example.com/web/agents-perception">Studies show agent systems influence human perception and trust</a>
          <a class="result__snippet">The strongest effects appear in guidance, framing and confidence transfer.</a>
          <a class="result__a" href="https://example.com/web/agents-behavior">Dialog agents shift behavior through recommendation framing</a>
          <a class="result__snippet">Behavioral outcomes depend on repetition, authority cues and anthropomorphic signals.</a>
        </body></html>
        """

        def fake_http_text(url: str) -> str:
            if "news.google.com" in url:
                return rss_xml
            if "duckduckgo" in url:
                return search_html
            raise AssertionError(f"unexpected url: {url}")

        with patch("nova.runtime.atheria_als._http_text", side_effect=fake_http_text), patch.object(
            self.shell.ai_runtime, "is_configured", side_effect=lambda provider: provider == "atheria"
        ), patch.object(
            self.shell.ai_runtime,
            "get_active_model",
            side_effect=lambda provider=None: "atheria-core" if provider == "atheria" else "",
        ), patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(
                output="Atheria haelt ihren letzten Resonanzzustand ohne neue Eingangssignale stabil.",
                data={
                    "text": "Atheria haelt ihren letzten Resonanzzustand ohne neue Eingangssignale stabil.",
                    "provider": "atheria",
                    "model": "atheria-core",
                },
                data_type=PipelineType.OBJECT,
            ),
        ):
            result = self.shell.route(
                'atheria als ask "wie viel einfluss haben Agenten systeme auf das verhalten und die wahrnehmung bei Menschen?"'
            )

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertIn('Zur Frage "wie viel einfluss haben Agenten systeme auf das verhalten und die wahrnehmung bei Menschen?"', payload["answer"])
        self.assertIn("frische RSS- und Websignale", payload["answer"])
        self.assertEqual(
            payload["source_titles"][:3],
            [
                "How conversational agents shape trust and compliance in users",
                "Agent systems can steer attention through adaptive dialogue patterns",
                "Studies show agent systems influence human perception and trust",
            ],
        )
        self.assertEqual(payload["probe"]["sensor_counts"]["rss"], 2)
        self.assertEqual(payload["probe"]["sensor_counts"]["web_search"], 2)
        self.assertNotIn("milk biomarkers", " ".join(payload["source_titles"]).lower())
        self.assertNotIn("ohne neue eingangssignale", payload["answer"].lower())

    def test_atheria_als_ask_persists_question_and_interpretation_to_chronik(self) -> None:
        configure = self.shell.route(
            'atheria als configure --analysis on --analysis-provider lmstudio --analysis-model local-model'
        )
        self.assertIsNone(configure.error)
        rss_xml = """
        <rss><channel>
          <item>
            <title>Agent systems influence perception through framing and authority cues</title>
            <description>Behavioral studies show repeated guidance can alter user judgement.</description>
            <link>https://example.com/rss/perception-framing</link>
            <pubDate>Thu, 20 Mar 2026 06:10:00 GMT</pubDate>
          </item>
        </channel></rss>
        """
        search_html = """
        <html><body>
          <a class="result__a" href="https://example.com/web/agents-social">Human perception shifts under dialog-agent recommendation pressure</a>
          <a class="result__snippet">Trust and salience change when systems sound confident and persistent.</a>
        </body></html>
        """

        def fake_http_text(url: str) -> str:
            if "news.google.com" in url:
                return rss_xml
            if "duckduckgo" in url:
                return search_html
            raise AssertionError(f"unexpected url: {url}")

        def fake_complete_prompt(prompt: str, *, provider: str, model: str | None = None, system_prompt: str | None = None) -> CommandResult:
            if provider == "atheria":
                return CommandResult(
                    output="Agentensysteme beeinflussen Wahrnehmung und Verhalten vor allem ueber Framing, Autoritaetssignale und Wiederholung.",
                    data={
                        "text": "Agentensysteme beeinflussen Wahrnehmung und Verhalten vor allem ueber Framing, Autoritaetssignale und Wiederholung.",
                        "provider": "atheria",
                        "model": "atheria-core",
                    },
                    data_type=PipelineType.OBJECT,
                )
            if provider == "lmstudio":
                return CommandResult(
                    output='{"statement":"Atheria beschreibt einen realen Einfluss von Agentensystemen auf Wahrnehmung und Verhalten.","meaning":"Die Evidenz zeigt, dass Dialogagenten ueber Framing und Vertrauenssignale menschliche Urteile mitpraegen koennen.","recommendation":"Die Quellen sollten nach Wirkungstaerke, Kontext und Risikogrenzen verglichen werden.","risk_level":"mittel","confidence":0.71}',
                    data={
                        "text": '{"statement":"Atheria beschreibt einen realen Einfluss von Agentensystemen auf Wahrnehmung und Verhalten.","meaning":"Die Evidenz zeigt, dass Dialogagenten ueber Framing und Vertrauenssignale menschliche Urteile mitpraegen koennen.","recommendation":"Die Quellen sollten nach Wirkungstaerke, Kontext und Risikogrenzen verglichen werden.","risk_level":"mittel","confidence":0.71}',
                        "provider": "lmstudio",
                        "model": "local-model",
                    },
                    data_type=PipelineType.OBJECT,
                )
            raise AssertionError(f"unexpected provider: {provider}")

        with patch("nova.runtime.atheria_als._http_text", side_effect=fake_http_text), patch.object(
            self.shell.ai_runtime, "is_configured", side_effect=lambda provider: provider in {"atheria", "lmstudio"}
        ), patch.object(
            self.shell.ai_runtime,
            "get_active_model",
            side_effect=lambda provider=None: "atheria-core" if provider == "atheria" else ("local-model" if provider == "lmstudio" else ""),
        ), patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete_prompt):
            result = self.shell.route(
                'atheria als ask "wie viel einfluss haben Agenten systeme auf das verhalten und die wahrnehmung bei Menschen?"'
            )

        self.assertIsNone(result.error)
        html = self.shell.als.chronik_html_path.read_text(encoding="utf-8")
        self.assertIn("Atheria beantwortete eine direkte Frage auf Basis frischer RSS- und Websignale.", html)
        self.assertIn("Frage: wie viel einfluss haben Agenten systeme auf das verhalten und die wahrnehmung bei Menschen?", html)
        self.assertIn("Agent systems influence perception through framing and authority cues", html)
        self.assertIn("Atheria formulierte:", html)
        self.assertIn("LM-Studio-Einordnung:", html)
        self.assertIn("Dialogagenten ueber Framing und Vertrauenssignale", html)

    def test_atheria_als_feedback_trains_and_logs_dialog(self) -> None:
        with patch.object(self.shell.atheria, "train_rows", return_value=1) as train_mock:
            result = self.shell.route('atheria als feedback "Focus more on GPU runtime anomalies."')

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["inserted_rows"], 1)
        self.assertEqual(payload["kind"], "feedback")
        self.assertEqual(payload["speech_act"]["mode"], "feedback")
        train_mock.assert_called_once()
        self.assertTrue(self.shell.als.dialog_path.exists())

    def test_atheria_als_stream_tail_returns_recent_events_without_crashing(self) -> None:
        event_rows = [
            {"event_id": "als_1", "summary": "first", "metrics": {"signal_strength": 0.10}},
            {"event_id": "als_2", "summary": "second", "metrics": {"signal_strength": 0.20}},
            {"event_id": "als_3", "summary": "third", "metrics": {"signal_strength": 0.30}},
            {"event_id": "als_4", "summary": "fourth", "metrics": {"signal_strength": 0.40}},
        ]
        for row in event_rows:
            self.shell.als._append_jsonl(self.shell.als.events_path, row)

        result = self.shell.route("atheria als stream tail --limit 3")

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(len(payload), 3)
        self.assertEqual([item["event_id"] for item in payload], ["als_2", "als_3", "als_4"])
        self.assertEqual(result.data_type, PipelineType.OBJECT)

    def test_atheria_als_search_returns_structured_web_results(self) -> None:
        search_html = """
        <html><body>
          <a class="result__a" href="https://example.com/agent-runtime">Agent runtime security for local AI infrastructure</a>
          <a class="result__snippet">A practical overview of runtime security and sovereign agent execution.</a>
          <a class="result__a" href="https://example.com/mesh-agents">Mesh workers improve agent orchestration</a>
          <a class="result__snippet">Distributed workers reduce latency and improve resilience for agent systems.</a>
        </body></html>
        """
        with patch("nova.runtime.atheria_als._http_text", return_value=search_html):
            result = self.shell.route('atheria als search "AI infrastructure agent runtime" --provider duckduckgo_html --limit 2')

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["query"], "AI infrastructure agent runtime")
        self.assertEqual(payload["provider"], "duckduckgo_html")
        self.assertEqual(payload["result_count"], 2)
        self.assertEqual(payload["results"][0]["sensor"], "web_search")
        self.assertEqual(payload["results"][0]["search_provider"], "duckduckgo_html")
        self.assertIn("duckduckgo.com", payload["search_url"])

    def test_atheria_als_cycle_ingests_web_search_results_when_enabled(self) -> None:
        search_html = """
        <html><body>
          <a class="result__a" href="https://example.com/runtime-1">Secure agent runtime expands across enterprise AI clusters</a>
          <a class="result__snippet">Signals point to stronger runtime-security demand across AI infrastructure.</a>
          <a class="result__a" href="https://example.com/runtime-2">Mesh orchestration improves resilient agent deployment</a>
          <a class="result__snippet">Distributed execution patterns lower pressure on local runtimes.</a>
        </body></html>
        """
        rss_xml = """
        <rss><channel>
          <item>
            <title>GPU capacity pressures continue in AI infrastructure</title>
            <description>Operations teams report increased demand for agent runtimes.</description>
            <link>https://example.com/rss-gpu-capacity</link>
            <pubDate>Wed, 19 Mar 2026 07:00:00 GMT</pubDate>
          </item>
        </channel></rss>
        """

        def fake_http_text(url: str) -> str:
            if "duckduckgo" in url:
                return search_html
            return rss_xml

        configure = self.shell.route(
            'atheria als configure --topic "AI infrastructure agent runtime" --web-search on --search-query "AI infrastructure agent runtime" --search-provider duckduckgo_html --search-limit 2'
        )
        self.assertIsNone(configure.error)
        with patch("nova.runtime.atheria_als._http_text", side_effect=fake_http_text):
            result = self.shell.route("atheria als cycle")

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["sensor_counts"]["web_search"], 2)
        self.assertGreaterEqual(payload["sensor_counts"]["rss"], 1)
        self.assertTrue(any(str(item.get("source", "")).startswith("web_search:duckduckgo_html") for item in payload["items"]))

    def test_atheria_voice_windows_backend_uses_plain_quoted_path_in_powershell(self) -> None:
        voice_runtime = AtheriaVoiceRuntime(Path(self._temp_home.name) / "voice_runtime")
        captured: dict[str, object] = {}

        def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            captured["command"] = list(command)
            captured["kwargs"] = dict(kwargs)
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        with patch("nova.runtime.atheria_als.os.name", "nt"), patch(
            "nova.runtime.atheria_als.subprocess.run",
            side_effect=fake_run,
        ):
            spoken, backend, error = voice_runtime._speak_windows(
                "Atheria spricht.",
                {"pitch_percent": 0, "rate": 0, "volume": 70},
                voice_name="Microsoft Hedda Desktop",
            )

        self.assertTrue(spoken)
        self.assertEqual(backend, "sapi")
        self.assertEqual(error, "")
        command = captured["command"]
        self.assertIsInstance(command, list)
        self.assertIn("-Command", command)
        powershell_script = str(command[-1])
        self.assertIn("Get-Content -Raw -Path '", powershell_script)
        self.assertNotIn("@'", powershell_script)
        self.assertIn("SpeakSsml", powershell_script)

    def test_atheria_voice_ssml_omits_empty_voice_wrapper_without_voice_name(self) -> None:
        voice_runtime = AtheriaVoiceRuntime(Path(self._temp_home.name) / "voice_runtime")

        ssml = voice_runtime._ssml(
            "Atheria & Analyse",
            {"pitch_percent": 1, "rate": 2, "volume": 80},
            voice_name="",
        )

        self.assertIn("<speak version='1.0' xml:lang='de-DE'>", ssml)
        self.assertIn("<prosody pitch='+1%' rate='+2%' volume='80'>Atheria &amp; Analyse</prosody>", ssml)
        self.assertNotIn("<voice>", ssml)
        self.assertNotIn("</voice>", ssml)

    def test_atheria_voice_ssml_uses_named_voice_wrapper_when_voice_is_configured(self) -> None:
        voice_runtime = AtheriaVoiceRuntime(Path(self._temp_home.name) / "voice_runtime")

        ssml = voice_runtime._ssml(
            "Atheria spricht.",
            {"pitch_percent": 0, "rate": 0, "volume": 70},
            voice_name="Microsoft Hedda Desktop",
        )

        self.assertIn('<voice name="Microsoft Hedda Desktop">', ssml)
        self.assertIn("</voice>", ssml)

    def test_cli_main_serve_atheria_als_once_routes_to_runtime(self) -> None:
        with patch("nova_shell.AtheriaALSRuntime.serve_forever", return_value=0) as serve_mock:
            exit_code = main(["--no-plugins", "--serve-atheria-als", "--als-once"])
        self.assertEqual(exit_code, 0)
        serve_mock.assert_called_once_with(once=True)

    def test_aion_chronik_html_converts_windows_report_root_to_fetchable_file_urls(self) -> None:
        module = runpy.run_path(str(Path("Atheria") / "aion_chronik.py"))
        html = module["_render_html"]([], report_root=Path(r"C:\Users\ralfk\.nova_shell_memory\atheria_als\daemon_runtime"))

        self.assertIn("function toFetchUrl(path)", html)
        self.assertIn('if (/^[A-Za-z]:\\//.test(value)) {', html)
        self.assertIn('return "file:///" + encodeURI(value).replace(/#/g, "%23");', html)
        self.assertIn("fetch(toFetchUrl(auditFile)", html)
        self.assertIn("fetch(toFetchUrl(resonanceFile)", html)

    def test_aion_chronik_html_preserves_embedded_resonance_when_local_fetch_fails(self) -> None:
        module = runpy.run_path(str(Path("Atheria") / "aion_chronik.py"))
        report_root = Path(self._temp_home.name) / "daemon_runtime"
        core_audit = report_root / "core_audit"
        core_audit.mkdir(parents=True, exist_ok=True)
        (core_audit / "nova-shell-als_inter_core_resonance.jsonl").write_text(
            json.dumps(
                {
                    "timestamp": 1773958203.2038045,
                    "observer_label": "Atheria Live Stream",
                    "trigger_asset": "SIGNAL",
                    "target_asset": "TEMPERATURE",
                    "lag_minutes": 0.0,
                    "invariant": {
                        "statement": "Atheria erkennt eine stabile Invariante im lokalen Resonanzfeld.",
                        "confidence": 0.81,
                        "mean_effect_size": 0.194,
                        "samples": 48,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        html = module["_render_html"]([], report_root=report_root)

        self.assertIn('id="chronik-resonance-card" data-embedded-resonance="1"', html)
        self.assertIn("function canUseEmbeddedResonance(activeReportDir)", html)
        self.assertIn("if (canUseEmbeddedResonance(activeReportDir)) {", html)
        self.assertIn("Atheria erkennt eine stabile Invariante im lokalen Resonanzfeld.", html)

    def test_tool_register_and_call_with_schema(self) -> None:
        register = self.shell.route(
            "tool register greet --description 'Greet user' "
            "--schema '{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}},\"required\":[\"name\"]}' "
            "--pipeline 'py \"Hello \" + {{py:name}}'"
        )
        self.assertIsNone(register.error)

        called = self.shell.route("tool call greet name=Nova")
        self.assertIsNone(called.error)
        self.assertEqual(called.output.strip(), "Hello Nova")

        dot_called = self.shell.route("tool.call greet name=Nova")
        self.assertIsNone(dot_called.error)
        self.assertEqual(dot_called.output.strip(), "Hello Nova")

        missing = self.shell.route("tool call greet")
        self.assertIsNotNone(missing.error)
        self.assertIn("missing required tool argument: name", missing.error)

    def test_tool_alias_commands_list_and_show(self) -> None:
        register = self.shell.route(
            "tool.register greet_alias --description 'Greet alias user' "
            "--schema '{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}},\"required\":[\"name\"]}' "
            "--pipeline 'py \"Hello \" + {{py:name}}'"
        )
        self.assertIsNone(register.error)

        listed = self.shell.route("tool.list")
        self.assertIsNone(listed.error)
        tools = json.loads(listed.output)
        self.assertTrue(any(tool["name"] == "greet_alias" for tool in tools))

        shown = self.shell.route("tool.show greet_alias")
        self.assertIsNone(shown.error)
        payload = json.loads(shown.output)
        self.assertEqual(payload["name"], "greet_alias")

    def test_ai_plan_prefers_registered_tool_candidate(self) -> None:
        self.shell.route(
            "tool register csv_average --description 'calculate csv average from file' "
            "--schema '{\"type\":\"object\",\"properties\":{\"file\":{\"type\":\"string\"}}}' "
            "--pipeline 'data load {{file}} | py sum(float(r[\"A\"]) for r in _) / len(_)'"
        )
        with patch.object(self.shell.ai_runtime, "get_active_provider", return_value=""):
            self.shell.ai_runtime.active_provider = ""
            self.shell.ai_runtime.active_model = ""
            result = self.shell.route('ai plan "calculate csv average"')
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "tool.call csv_average")
        self.assertEqual(result.data["mode"], "heuristic-tool")

    def test_ai_plan_uses_provider_json_when_available(self) -> None:
        with patch.object(self.shell.ai_runtime, "get_active_provider", return_value="lmstudio"), patch.object(
            self.shell.ai_runtime,
            "get_active_model",
            return_value="planner-model",
        ), patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(
                output='{"steps":[{"tool":"dataset_summarize","args":{"file":"items.csv"}}],"summary":"use summarize","mode":"provider","tools":["dataset_summarize"],"agents":[],"memory_ids":[]}\n',
                data={"text": "ignored"},
                data_type=PipelineType.OBJECT,
            ),
        ):
            result = self.shell.route('ai plan "summarize the latest dataset"')
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "tool.call dataset_summarize file=items.csv")
        self.assertEqual(result.data["summary"], "use summarize")
        self.assertEqual(result.data["steps"][0]["tool"], "dataset_summarize")

    def test_ai_plan_builds_tool_graph_for_csv_average(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.shell.ai_runtime, "get_active_provider", return_value=""):
            tmp_path = Path(tmp)
            csv_file = tmp_path / "items.csv"
            csv_file.write_text("id,name,price\n1,Brot,2.50\n2,Käse,4.20\n3,Apfel,1.10\n", encoding="utf-8")
            self.shell.cwd = tmp_path
            self.shell.ai_runtime.cwd = tmp_path
            result = self.shell.route('ai plan "calculate average price in items.csv"')

        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "tool.call csv_load file=items.csv | tool.call table_mean column=price")
        self.assertEqual(result.data["mode"], "heuristic-tool-graph")
        self.assertEqual([step["tool"] for step in result.data["steps"]], ["csv_load", "table_mean"])

    def test_ai_plan_run_executes_tool_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.shell.ai_runtime, "get_active_provider", return_value=""):
            tmp_path = Path(tmp)
            csv_file = tmp_path / "items.csv"
            csv_file.write_text("id,name,price\n1,Brot,2.50\n2,Käse,4.20\n3,Apfel,1.10\n", encoding="utf-8")
            self.shell.cwd = tmp_path
            self.shell.ai_runtime.cwd = tmp_path
            result = self.shell.route('ai plan --run "calculate average price in items.csv"')

        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "2.6")
        self.assertEqual(result.data["pipeline"], "tool.call csv_load file=items.csv | tool.call table_mean column=price")
        self.assertEqual(result.data["execution"]["output"], "2.6")

    def test_ai_plan_run_repairs_invalid_provider_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_file = tmp_path / "items.csv"
            csv_file.write_text("id,name,price\n1,Brot,2.50\n2,Käse,4.20\n3,Apfel,1.10\n", encoding="utf-8")
            self.shell.cwd = tmp_path
            self.shell.ai_runtime.cwd = tmp_path

            responses = iter(
                [
                    CommandResult(
                        output='{"steps":[{"tool":"csv_load","args":{"file":"items.csv"}},{"tool":"table_mean","args":{}}],"summary":"broken plan","mode":"provider"}\n',
                        data={"text": "broken plan"},
                        data_type=PipelineType.OBJECT,
                    ),
                    CommandResult(
                        output='{"steps":[{"tool":"csv_load","args":{"file":"items.csv"}},{"tool":"table_mean","args":{"column":"price"}}],"summary":"repaired plan","mode":"provider-repair"}\n',
                        data={"text": "repaired plan"},
                        data_type=PipelineType.OBJECT,
                    ),
                ]
            )

            with patch.object(self.shell.ai_runtime, "get_active_provider", return_value="lmstudio"), patch.object(
                self.shell.ai_runtime,
                "get_active_model",
                return_value="planner-model",
            ), patch.object(
                self.shell.ai_runtime,
                "complete_prompt",
                side_effect=lambda *args, **kwargs: next(responses),
            ):
                result = self.shell.route('ai plan --run --retries 2 "calculate average price in items.csv"')

        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "2.6")
        self.assertEqual(result.data["execution"]["output"], "2.6")
        self.assertTrue(result.data["replanned"])
        self.assertEqual(result.data["attempts"][0]["status"], "validation_failed")

    def test_ai_prompt_with_pipeline_data_adds_context(self) -> None:
        calls: list[str] = []

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            calls.append(prompt)
            return CommandResult(output="summary\n", data={"text": "summary"}, data_type=PipelineType.OBJECT)

        with tempfile.TemporaryDirectory() as tmp, patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            csv_file = Path(tmp) / "items.csv"
            csv_file.write_text("id,name,price\n1,Brot,2.50\n2,Käse,4.20\n", encoding="utf-8")
            result = self.shell.route(f'data load {csv_file} | ai prompt "Summarize this dataset"')

        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "summary")
        self.assertEqual(len(calls), 1)
        self.assertIn("Nova-shell context", calls[0])
        self.assertIn("Brot", calls[0])

    def test_ai_prompt_file_option_uses_shell_cwd(self) -> None:
        calls: list[str] = []

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            calls.append(prompt)
            return CommandResult(output="file-summary\n", data={"text": "file-summary"}, data_type=PipelineType.OBJECT)

        with tempfile.TemporaryDirectory() as tmp, patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            tmp_path = Path(tmp)
            csv_file = tmp_path / "items.csv"
            csv_file.write_text("id,name,price\n1,Brot,2.50\n", encoding="utf-8")
            self.shell.cwd = tmp_path
            self.shell.ai_runtime.cwd = tmp_path
            result = self.shell.route('ai prompt --file items.csv "Summarize this dataset"')

        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "file-summary")
        self.assertEqual(len(calls), 1)
        self.assertIn("preview_rows", calls[0])
        self.assertIn("Brot", calls[0])

    def test_ai_prompt_dataset_without_context_returns_guidance(self) -> None:
        with patch.object(self.shell.ai_runtime, "complete_prompt") as complete_mock:
            result = self.shell.route('ai prompt "Summarize this dataset"')
        self.assertIsNotNone(result.error)
        self.assertIn("dataset context missing", result.error)
        complete_mock.assert_not_called()

    def test_agent_create_and_run(self) -> None:
        calls: list[dict[str, str]] = []

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            calls.append({"prompt": prompt, "provider": provider or "", "model": model or "", "system_prompt": system_prompt})
            return CommandResult(output="agent-response\n", data={"text": "agent-response"}, data_type=PipelineType.OBJECT)

        with patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            create = self.shell.route('agent create helper "Summarize {{input}}" --provider lmstudio --model local-model --system "You are precise."')
            self.assertIsNone(create.error)
            run = self.shell.route("agent run helper quarterly report")
            self.assertIsNone(run.error)
            self.assertEqual(run.output.strip(), "agent-response")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["provider"], "lmstudio")
        self.assertEqual(calls[0]["model"], "local-model")
        self.assertEqual(calls[0]["system_prompt"], "You are precise.")
        self.assertIn("quarterly report", calls[0]["prompt"])

    def test_ns_run_registers_declarative_agents_for_agent_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "standalone_agents.ns"
            script_path.write_text(
                """
agent helper {
  provider: atheria
  model: atheria-core
  system_prompt: "You are concise."
  prompts: {v1: "Summarize {{input}}"}
  prompt_version: v1
}
""".strip(),
                encoding="utf-8",
            )
            with patch.object(
                self.shell.ai_runtime,
                "complete_prompt",
                return_value=CommandResult(output="ok\n", data={"text": "ok"}, data_type=PipelineType.OBJECT),
            ):
                result = self.shell.route(f"ns.run {script_path}")
                self.assertIsNone(result.error)
                listing = json.loads(self.shell.route("agent list").output)
                names = {item["name"] for item in listing}
                self.assertIn("helper", names)
                self.assertIn("standalone_agents.helper", names)

                run_result = self.shell.route("agent run helper quarterly report")
                self.assertIsNone(run_result.error)
                self.assertEqual(run_result.output.strip(), "ok")
            with suppress(Exception):
                if self.shell._declarative_nova is not None:
                    self.shell._declarative_nova.close()
                    self.shell._declarative_nova = None

    def test_generate_agent_skills_examples_creates_standalone_skill_agents(self) -> None:
        root = Path(__file__).resolve().parents[1]
        generator = runpy.run_path(str(root / "scripts" / "generate_agent_skills_examples.py"))
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            manifest = generator["generate_examples"](root / "agent-skills-main" / "skills", output_dir)
            react_payload = manifest["react-best-practices"]
            self.assertGreaterEqual(int(react_payload["agent_count"]), 40)
            self.assertNotIn("deploy-to-vercel", manifest)
            self.assertNotIn("vercel-cli-with-tokens", manifest)
            self.assertNotIn("web-design-guidelines", manifest)
            target = output_dir / str(react_payload["file_name"])
            self.assertTrue(target.exists())
            source = target.read_text(encoding="utf-8")
            self.assertNotIn("agent-skills-main", source)
            self.assertIn("provider: shell", source)
            self.assertIn("Patch:", source)
            self.assertIn("Promise.all([", source)

            result = self.shell.route(f"ns.run {target}")
            self.assertIsNone(result.error)
            loaded_payload = json.loads(result.output)
            self.assertEqual(loaded_payload["mode"], "agent_bundle")
            self.assertIn("react_best_practices_async_parallel", loaded_payload["agents"])
            listing = json.loads(self.shell.route("agent list").output)
            names = {item["name"] for item in listing}
            self.assertIn("react_best_practices_router", names)
            self.assertIn("react_best_practices_async_parallel", names)
            with suppress(Exception):
                if self.shell._declarative_nova is not None:
                    self.shell._declarative_nova.close()
                    self.shell._declarative_nova = None

    def test_ns_skills_build_generates_examples_from_skill_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_root = root / "agent-skills-main" / "skills"
            skill_dir = skills_root / "demo-skill"
            rules_dir = skill_dir / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                """---
name: demo-skill
description: Demo skill.
---

# Demo Skill

Use this skill for demos.
""",
                encoding="utf-8",
            )
            (rules_dir / "focus.md").write_text(
                """---
title: Focus Rule
impact: HIGH
tags: demo, focus
---

# Focus Rule

Prefer focused changes with concrete reasoning.
""",
                encoding="utf-8",
            )
            output_dir = root / "generated"
            result = self.shell.route(f"ns.skills build {root / 'agent-skills-main'} {output_dir}")
            self.assertIsNone(result.error)
            payload = json.loads(result.output)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["skipped"], {})
            target = output_dir / "demo_skill_agents.ns"
            self.assertTrue(target.exists())
            source = target.read_text(encoding="utf-8")
            self.assertIn("agent demo_skill_focus", source)
            self.assertNotIn("agent-skills-main", source)
            self.assertIn("provider: shell", source)
            self.assertIn("Patch:", source)

    def test_ns_run_agent_bundle_returns_compact_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_path = root / "bundle.ns"
            script_path.write_text(
                """
state helper_memory {
  backend: atheria
  namespace: helper
}

agent helper {
  provider: shell
  model: active
  memory: helper_memory
  system_prompt: "You are concise."
  prompts: {v1: "Summarize {{input}}"}
  prompt_version: v1
}
""".strip(),
                encoding="utf-8",
            )
            result = self.shell.route(f"ns.run {script_path}")
            try:
                if self.shell._declarative_nova is not None:
                    self.shell._declarative_nova.close()
                    self.shell._declarative_nova = None
            except Exception:
                pass

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["mode"], "agent_bundle")
        self.assertEqual(payload["agent_count"], 1)
        self.assertIn("helper", payload["agents"])

    def _copy_ceo_runtime_fixture(self, target_root: Path) -> None:
        source_root = Path(__file__).resolve().parents[1] / "examples" / "CEO_ns"
        for name in (
            "CEO_Lifecycle.ns",
            "ceo_runtime_helper.py",
            "ceo_continuous_runtime.py",
            "internal_telemetry.json",
            "external_market_signals.json",
            "event_signals.json",
            "policy_overrides.json",
        ):
            (target_root / name).write_text((source_root / name).read_text(encoding="utf-8"), encoding="utf-8")

    def test_ceo_ns_examples_load_successfully(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ceo_dir = root / "examples" / "CEO_ns"
        targets = sorted(ceo_dir.glob("*.ns"))
        self.assertGreaterEqual(len(targets), 9)

        for target in targets:
            result = self.shell.route(f'ns.run "{target}"')
            try:
                self.assertIsNone(result.error, f"{target.name}: {result.error}")
                payload = json.loads(result.output)
                if target.name == "CEO_Lifecycle.ns":
                    self.assertEqual(payload["mode"], "ceo_lifecycle")
                    self.assertEqual(payload["flow"], "ceo_lifecycle")
                    self.assertIn("execution_plan", payload)
                    self.assertIsInstance(payload["execution_plan"], dict)
                    self.assertIn("decision_packet", payload)
                    self.assertIsInstance(payload["decision_packet"], dict)
                    self.assertIn("artifact_paths", payload)
                    self.assertIsInstance(payload["artifact_paths"], dict)
                    self.assertTrue(Path(payload["artifact_paths"]["report_path"]).is_file())
                    self.assertTrue(Path(payload["artifact_paths"]["html_path"]).is_file())
                    self.assertGreaterEqual(int(payload["history_length"]), 1)
                    self.assertEqual(payload["status_command"], "ns.status")
                else:
                    self.assertEqual(payload["mode"], "agent_bundle")
                    self.assertEqual(payload["agent_count"], 1)
            finally:
                with suppress(Exception):
                    if self.shell._declarative_nova is not None:
                        self.shell._declarative_nova.close()
                        self.shell._declarative_nova = None

    def test_declarative_py_exec_can_import_local_helper_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "local_helper.py").write_text(
                "def load_value():\n"
                "    return {'status': 'ok', 'source': 'local-helper'}\n",
                encoding="utf-8",
            )
            script = root / "import_demo.ns"
            script.write_text(
                """flow demo {
  py.exec "import local_helper as helper; _ = helper.load_value()" -> imported_value
}
""",
                encoding="utf-8",
            )

            result = self.shell.route(f'ns.run "{script}"')
            try:
                self.assertIsNone(result.error)
                payload = json.loads(result.output)
                self.assertEqual(payload["flows"][0]["flow"], "demo")
                self.assertEqual(payload["context"]["outputs"]["imported_value"]["status"], "ok")
                self.assertEqual(payload["context"]["outputs"]["imported_value"]["source"], "local-helper")
            finally:
                with suppress(Exception):
                    if self.shell._declarative_nova is not None:
                        self.shell._declarative_nova.close()
                        self.shell._declarative_nova = None

    def test_ceo_lifecycle_respects_governance_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._copy_ceo_runtime_fixture(root)
            (root / "policy_overrides.json").write_text(
                json.dumps(
                    {
                        "max_risk": 0.2,
                        "capital_limit": 90000,
                        "minimum_runway_months": 4.0,
                        "forbidden_actions": ["scale_enterprise_capacity"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = self.shell.route(f'ns.run "{root / "CEO_Lifecycle.ns"}"')
            try:
                self.assertIsNone(result.error)
                payload = json.loads(result.output)
                decision = payload["decision_packet"]
                self.assertEqual(decision["decision"], "revise")
                self.assertTrue(decision["selected_option"]["blocks"])
                capital_event = payload["capital_event"]
                self.assertTrue(capital_event["active"])
            finally:
                with suppress(Exception):
                    if self.shell._declarative_nova is not None:
                        self.shell._declarative_nova.close()
                        self.shell._declarative_nova = None

    def test_ceo_lifecycle_is_consistent_for_identical_inputs(self) -> None:
        decisions: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            for root_text in (tmp_a, tmp_b):
                root = Path(root_text)
                self._copy_ceo_runtime_fixture(root)
                result = self.shell.route(f'ns.run "{root / "CEO_Lifecycle.ns"}"')
                try:
                    self.assertIsNone(result.error)
                    payload = json.loads(result.output)
                    decision = dict(payload["decision_packet"])
                    selected = dict(decision.get("selected_option") or {})
                    decisions.append(
                        {
                            "decision": decision.get("decision"),
                            "recommended_action": decision.get("recommended_action"),
                            "selected_option": selected.get("option_id"),
                            "score": decision.get("score"),
                        }
                    )
                finally:
                    with suppress(Exception):
                        if self.shell._declarative_nova is not None:
                            self.shell._declarative_nova.close()
                            self.shell._declarative_nova = None

        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[0], decisions[1])

    def test_ceo_lifecycle_blocks_when_capital_limit_is_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._copy_ceo_runtime_fixture(root)
            (root / "policy_overrides.json").write_text(
                json.dumps(
                    {
                        "max_risk": 0.95,
                        "capital_limit": 100000,
                        "minimum_runway_months": 1.0,
                        "forbidden_actions": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            result = self.shell.route(f'ns.run "{root / "CEO_Lifecycle.ns"}"')
            try:
                self.assertIsNone(result.error)
                payload = json.loads(result.output)
                decision = payload["decision_packet"]
                self.assertEqual(decision["decision"], "revise")
                self.assertIn("Kapitalgrenze ueberschritten", decision["selected_option"]["blocks"])
            finally:
                with suppress(Exception):
                    if self.shell._declarative_nova is not None:
                        self.shell._declarative_nova.close()
                        self.shell._declarative_nova = None

    def test_ceo_lifecycle_compact_summary_keeps_full_runtime_in_ns_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._copy_ceo_runtime_fixture(root)
            result = self.shell.route(f'ns.run "{root / "CEO_Lifecycle.ns"}"')
            try:
                self.assertIsNone(result.error)
                payload = json.loads(result.output)
                self.assertEqual(payload["mode"], "ceo_lifecycle")
                self.assertNotIn("context", payload)

                status_result = self.shell.route("ns.status")
                self.assertIsNone(status_result.error)
                status_payload = json.loads(status_result.output)
                self.assertIn("decision_packet", status_payload["context"]["outputs"])
                self.assertIn("ceo_report", status_payload["context"]["outputs"])
                self.assertIn("final_state", status_payload["context"]["outputs"])
            finally:
                with suppress(Exception):
                    if self.shell._declarative_nova is not None:
                        self.shell._declarative_nova.close()
                        self.shell._declarative_nova = None

    def test_ceo_continuous_runtime_writes_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._copy_ceo_runtime_fixture(root)
            runner = runpy.run_path(str(root / "ceo_continuous_runtime.py"))
            status = runner["run_cycle"](1)
            self.assertEqual(status["cycle"], 1)
            self.assertGreaterEqual(int(status["flow_count"]), 1)
            self.assertIn("decision_packet", dict(status.get("outputs") or {}))
            status_path = root / ".nova_ceo" / "continuous_status.json"
            self.assertTrue(status_path.is_file())
            persisted = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["cycle"], 1)
            self.assertIn("execution_plan", dict(persisted.get("outputs") or {}))

    def test_decision_lifecycle_template_loads_and_graphs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        target = root / "examples" / "decision_lifecycle_template.ns"

        run_result = self.shell.route(f'ns.run "{target}"')
        self.assertIsNone(run_result.error)
        run_payload = json.loads(run_result.output)
        self.assertEqual(run_payload["flows"][0]["flow"], "decision_cycle")
        self.assertIn("action_plan", run_payload["context"]["outputs"])
        self.assertIsInstance(run_payload["context"]["outputs"]["action_plan"], str)

        graph_result = self.shell.route(f'ns.graph "{target}"')
        self.assertIsNone(graph_result.error)
        graph_payload = json.loads(graph_result.output)
        self.assertIn("graph", graph_payload)
        node_names = {node.get("name") or node.get("id") for node in graph_payload["graph"]["nodes"]}
        self.assertTrue(any("DecisionAgent" in str(name) for name in node_names))
        self.assertTrue(any("ActionAgent" in str(name) for name in node_names))

    def test_ns_skills_build_uses_runtime_generators_without_script_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_root = root / "agent-skills-main" / "skills"
            skill_dir = skills_root / "demo-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                """---
name: demo-skill
description: Demo skill.
---

# Demo Skill

Use this skill for demos.
""",
                encoding="utf-8",
            )
            output_dir = root / "generated"
            import nova_shell as nova_shell_module

            called: dict[str, object] = {}

            def _inspect(path: Path) -> dict[str, dict[str, dict[str, object]]]:
                called["inspect"] = str(path)
                return {"portable": {"demo-skill": {"skill": "demo-skill"}}, "skipped": {}}

            def _generate(skills: Path, output: Path) -> dict[str, dict[str, object]]:
                called["generate"] = (str(skills), str(output))
                output.mkdir(parents=True, exist_ok=True)
                target = output / "demo_skill_agents.ns"
                target.write_text(
                    """state demo_skill_memory {
  backend: atheria
  namespace: demo_skill
}

agent demo_skill_generalist {
  provider: atheria
  model: atheria-core
  memory: demo_skill_memory
  system_prompt: "demo"
  prompts: {v1: "demo {{input}}"}
  prompt_version: v1
}
""",
                    encoding="utf-8",
                )
                return {
                    "demo-skill": {
                        "skill": "demo-skill",
                        "agent_count": 1,
                        "router": "",
                        "agents": ["demo_skill_generalist"],
                        "portable": True,
                        "file_name": target.name,
                        "path": str(target),
                    }
                }

            with (
                patch.object(nova_shell_module, "inspect_skill_examples", side_effect=_inspect),
                patch.object(nova_shell_module, "generate_skill_examples", side_effect=_generate),
            ):
                result = self.shell.route(f"ns.skills build {root / 'agent-skills-main'} {output_dir}")

            self.assertIsNone(result.error)
            self.assertIn("inspect", called)
            self.assertIn("generate", called)
            payload = json.loads(result.output)
            self.assertEqual(payload["count"], 1)
            self.assertTrue((output_dir / "demo_skill_agents.ns").exists())

    def test_ns_skills_build_returns_error_instead_of_crashing_on_generation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_root = root / "agent-skills-main" / "skills"
            skill_dir = skills_root / "demo-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text("# Demo Skill\n", encoding="utf-8")
            import nova_shell as nova_shell_module

            with patch.object(nova_shell_module, "inspect_skill_examples", side_effect=RuntimeError("generator boom")):
                result = self.shell.route(f"ns.skills build {root / 'agent-skills-main'}")

            self.assertEqual(result.error, "generator boom")

    def test_generate_agent_skills_examples_script_runs_from_repo_root(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "generate_agent_skills_examples.py"),
                    "--skills-root",
                    str(root / "agent-skills-main" / "skills"),
                    "--output-dir",
                    tmp,
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertIn("react-best-practices", payload["generated"])
            self.assertIn("deploy-to-vercel", payload["skipped"])
            self.assertIn("web-design-guidelines", payload["skipped"])
            self.assertTrue((Path(tmp) / "react_best_practices_agents.ns").exists())
            self.assertFalse((Path(tmp) / "deploy_to_vercel_agents.ns").exists())
            self.assertFalse((Path(tmp) / "web_design_guidelines_agents.ns").exists())

    def test_run_agent_once_with_shell_provider_uses_active_generative_provider(self) -> None:
        agent = AIAgentDefinition(
            name="skill_agent",
            prompt_template="Review {{input}}",
            provider="shell",
            model="active",
            system_prompt="Be concise.",
        )
        with patch.object(
            self.shell.ai_runtime,
            "complete_prompt",
            return_value=CommandResult(output="fixed\n", data={"provider": "lmstudio", "model": "local-model"}, data_type=PipelineType.OBJECT),
        ) as mocked_complete, patch.object(self.shell.ai_runtime, "get_active_provider", return_value="lmstudio"), patch.object(
            self.shell.ai_runtime,
            "get_active_model",
            return_value="local-model",
        ):
            result = self.shell._run_agent_once(agent, "const user = await fetchUser();")

        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "fixed")
        mocked_complete.assert_called_once()
        self.assertEqual(mocked_complete.call_args.kwargs["provider"], "lmstudio")
        self.assertEqual(mocked_complete.call_args.kwargs["model"], "local-model")
        self.assertEqual(mocked_complete.call_args.kwargs["system_prompt"], "Be concise.")

    def test_run_agent_once_with_shell_provider_requires_non_atheria_provider(self) -> None:
        agent = AIAgentDefinition(
            name="skill_agent",
            prompt_template="Review {{input}}",
            provider="shell",
            model="active",
            system_prompt="Be concise.",
        )
        with patch.object(self.shell.ai_runtime, "get_active_provider", return_value="atheria"):
            result = self.shell._run_agent_once(agent, "const user = await fetchUser();")

        self.assertIn("configured generative ai provider", str(result.error))

    def test_generate_agent_skills_examples_reports_nonportable_skills(self) -> None:
        root = Path(__file__).resolve().parents[1]
        generator = runpy.run_path(str(root / "scripts" / "generate_agent_skills_examples.py"))
        inventory = generator["inspect_skills"](root / "agent-skills-main" / "skills")
        self.assertIn("deploy-to-vercel", inventory["skipped"])
        self.assertIn("vercel-cli-with-tokens", inventory["skipped"])
        self.assertIn("web-design-guidelines", inventory["skipped"])
        self.assertIn("external", " ".join(inventory["skipped"]["deploy-to-vercel"]["reasons"]).lower())

    def test_agent_spawn_and_message_preserves_history(self) -> None:
        calls: list[str] = []
        replies = iter(["draft-1", "draft-2"])

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            calls.append(prompt)
            return CommandResult(output=next(replies) + "\n", data={"text": "ok"}, data_type=PipelineType.OBJECT)

        with patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            create = self.shell.route('agent create analyst "Summarize {{input}}" --provider lmstudio --model local-model')
            self.assertIsNone(create.error)
            spawned = self.shell.route("agent spawn analyst_rt --from analyst")
            self.assertIsNone(spawned.error)
            first = self.shell.route("agent message analyst_rt first report")
            self.assertIsNone(first.error)
            second = self.shell.route("agent message analyst_rt follow up")
            self.assertIsNone(second.error)

        self.assertEqual(first.output.strip(), "draft-1")
        self.assertEqual(second.output.strip(), "draft-2")
        self.assertEqual(len(calls), 2)
        self.assertIn("first report", calls[1])
        self.assertIn("draft-1", calls[1])

    def test_agent_run_supports_file_context_injection(self) -> None:
        calls: list[str] = []

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            calls.append(prompt)
            return CommandResult(output="ok\n", data={"text": "ok"}, data_type=PipelineType.OBJECT)

        with tempfile.TemporaryDirectory() as tmp, patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            tmp_path = Path(tmp)
            transcript = tmp_path / "script.md"
            transcript.write_text("# Intro\nSprecher 1: Willkommen bei Nova-shell.\n", encoding="utf-8")
            self.assertIsNone(self.shell.route('agent create helper "Quote {{input}}" --provider lmstudio --model local-model').error)
            run = self.shell.route(f'agent run helper --file {transcript} "Gib mir die Einleitung."')

        self.assertIsNone(run.error)
        self.assertEqual(run.output.strip(), "ok")
        self.assertEqual(len(calls), 1)
        self.assertIn("Gib mir die Einleitung.", calls[0])
        self.assertIn("Nova-shell locked context", calls[0])
        self.assertIn("Sprecher 1: Willkommen bei Nova-shell.", calls[0])

    def test_agent_message_supports_memory_context_from_source_file(self) -> None:
        calls: list[str] = []

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            calls.append(prompt)
            return CommandResult(output="monitor-ok\n", data={"text": "monitor-ok"}, data_type=PipelineType.OBJECT)

        with tempfile.TemporaryDirectory() as tmp, patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            tmp_path = Path(tmp)
            transcript = tmp_path / "final.md"
            transcript.write_text("Sprecher 1: Dies ist die exakte Einleitung.\n", encoding="utf-8")
            self.shell.cwd = tmp_path
            self.shell.ai_runtime.cwd = tmp_path

            embedded = self.shell.route("memory embed --id final_transcript --file final.md")
            self.assertIsNone(embedded.error)
            self.assertIsNone(
                self.shell.route(
                    'agent create script_monitor "Nutze nur {{input}}" --provider lmstudio --model local-model'
                ).error
            )
            self.assertIsNone(self.shell.route("agent spawn script_monitor_rt --from script_monitor").error)
            message = self.shell.route('agent message script_monitor_rt --memory final_transcript "Gib mir die Einleitung von Sprecher 1."')

        self.assertIsNone(message.error)
        self.assertEqual(message.output.strip(), "monitor-ok")
        self.assertEqual(len(calls), 1)
        self.assertIn("Gib mir die Einleitung von Sprecher 1.", calls[0])
        self.assertIn("Nova-shell locked context", calls[0])
        self.assertIn("Sprecher 1: Dies ist die exakte Einleitung.", calls[0])

    def test_agent_workflow_runs_agents_in_sequence(self) -> None:
        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            if prompt.startswith("Analyze"):
                return CommandResult(output="analysis\n", data={"text": "analysis"}, data_type=PipelineType.OBJECT)
            if prompt.startswith("Review"):
                return CommandResult(output="reviewed analysis\n", data={"text": "reviewed analysis"}, data_type=PipelineType.OBJECT)
            return CommandResult(output="fallback\n", data={"text": "fallback"}, data_type=PipelineType.OBJECT)

        with patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            self.assertIsNone(self.shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model local-model').error)
            self.assertIsNone(self.shell.route('agent create reviewer "Review {{input}}" --provider lmstudio --model local-model').error)
            workflow = self.shell.route('agent workflow --agents analyst,reviewer --input "quarterly report"')

        self.assertIsNone(workflow.error)
        self.assertEqual(workflow.output.strip(), "reviewed analysis")
        self.assertEqual(len(workflow.data["steps"]), 2)
        self.assertEqual(workflow.data["steps"][0]["output"], "analysis")
        self.assertEqual(workflow.data["steps"][1]["output"], "reviewed analysis")

    def test_agent_graph_runs_nodes_in_topological_order(self) -> None:
        calls: list[dict[str, str]] = []

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            calls.append({"prompt": prompt, "model": model or "", "provider": provider or ""})
            if model == "analyst-model":
                return CommandResult(output=f"analysis:{prompt}\n", data={"text": prompt}, data_type=PipelineType.OBJECT)
            if model == "reviewer-model":
                return CommandResult(output=f"review:{prompt}\n", data={"text": prompt}, data_type=PipelineType.OBJECT)
            return CommandResult(output=f"default:{prompt}\n", data={"text": prompt}, data_type=PipelineType.OBJECT)

        with patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            self.assertIsNone(self.shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model analyst-model').error)
            self.assertIsNone(self.shell.route('agent create reviewer "Review {{input}}" --provider lmstudio --model reviewer-model').error)
            created = self.shell.route("agent graph create review_chain --nodes analyst,reviewer")
            self.assertIsNone(created.error)
            run = self.shell.route('agent graph run review_chain --input "quarterly report"')

        self.assertIsNone(run.error)
        self.assertEqual(run.output.strip(), "review:Review analysis:Analyze quarterly report")
        self.assertEqual(len(run.data["steps"]), 2)
        self.assertEqual(run.data["steps"][0]["node"], "analyst")
        self.assertEqual(run.data["steps"][0]["input"], "quarterly report")
        self.assertEqual(run.data["steps"][1]["node"], "reviewer")
        self.assertEqual(run.data["steps"][1]["input"], "analysis:Analyze quarterly report")
        self.assertEqual([call["model"] for call in calls], ["analyst-model", "reviewer-model"])

    def test_agent_graph_swarm_routes_steps_over_mesh(self) -> None:
        remote_calls: list[tuple[str, str]] = []

        def fake_remote(worker_url: str, command: str) -> CommandResult:
            remote_calls.append((worker_url, command))
            if command.startswith("agent create"):
                return CommandResult(output="created\n", data={"ok": True}, data_type=PipelineType.OBJECT)
            if "quarterly report" in command:
                return CommandResult(output="analysis\n", data={"text": "analysis"}, data_type=PipelineType.OBJECT)
            return CommandResult(output="reviewed analysis\n", data={"text": "reviewed analysis"}, data_type=PipelineType.OBJECT)

        self.assertIsNone(self.shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model analyst-model').error)
        self.assertIsNone(self.shell.route('agent create reviewer "Review {{input}}" --provider lmstudio --model reviewer-model').error)
        self.assertIsNone(self.shell.route("agent graph create review_chain --nodes analyst,reviewer").error)
        self.shell.mesh.add_worker("http://worker-a", {"cpu", "py", "ai"})

        with patch.object(self.shell.remote, "execute", side_effect=fake_remote):
            run = self.shell.route('agent graph run review_chain --swarm --input "quarterly report"')

        self.assertIsNone(run.error)
        self.assertEqual(run.output.strip(), "reviewed analysis")
        self.assertTrue(run.data["swarm"])
        self.assertEqual(len(run.data["assignments"]), 2)
        self.assertTrue(all(item["mode"] == "mesh" for item in run.data["assignments"]))
        self.assertTrue(any(command.startswith("agent create") for _, command in remote_calls))
        self.assertTrue(any(command.startswith("agent run") for _, command in remote_calls))

    def test_mycelia_population_create_tick_and_fitness(self) -> None:
        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            if "Review" in prompt:
                return CommandResult(output="edge ai review with evidence\n", data={"text": "review"}, data_type=PipelineType.OBJECT)
            return CommandResult(output="edge ai analysis with evidence\n", data={"text": "analysis"}, data_type=PipelineType.OBJECT)

        with patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            self.assertIsNone(self.shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model local-model').error)
            self.assertIsNone(self.shell.route('agent create reviewer "Review {{input}}" --provider lmstudio --model local-model').error)
            self.assertIsNone(
                self.shell.route(
                    'tool register edge_report --description "edge ai report summarizer" --schema \'{"type":"object"}\' --pipeline \'py "ok"\''
                ).error
            )
            self.assertIsNone(self.shell.route('atheria sensor spawn edge_ai --template RSS_Base --name edge_watch').error)

            created = self.shell.route('mycelia population create colony --goal "edge ai operations report" --seed analyst,reviewer --target-size 3')
            tick = self.shell.route('mycelia population tick colony --input "edge ai trend shift" --cycles 1')
            fitness = self.shell.route("mycelia fitness colony")

        self.assertIsNone(created.error)
        created_payload = json.loads(created.output)
        self.assertEqual(created_payload["population"]["name"], "colony")
        self.assertEqual(len(created_payload["seeded_members"]), 2)

        self.assertIsNone(tick.error)
        tick_payload = json.loads(tick.output)
        self.assertEqual(tick_payload["population"], "colony")
        cycle = tick_payload["cycles"][0]
        self.assertGreaterEqual(len(cycle["fitness"]), 3)
        self.assertTrue(any(item["modules"]["tools"] for item in cycle["evaluations"]))
        self.assertTrue(any(item["modules"]["sensors"] for item in cycle["evaluations"]))
        self.assertGreaterEqual(cycle["population"]["species_count"], 1)

        self.assertIsNone(fitness.error)
        fitness_payload = json.loads(fitness.output)
        self.assertGreaterEqual(len(fitness_payload), 3)
        self.assertIn("average_fitness", fitness_payload[0])

    def test_mycelia_select_and_lineage_preserve_species_champions(self) -> None:
        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            if "Review" in prompt:
                return CommandResult(output="review with evidence\n", data={"text": "review"}, data_type=PipelineType.OBJECT)
            return CommandResult(output="analysis with evidence\n", data={"text": "analysis"}, data_type=PipelineType.OBJECT)

        with patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            self.assertIsNone(self.shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model local-model').error)
            self.assertIsNone(self.shell.route('agent create reviewer "Review {{input}}" --provider lmstudio --model local-model').error)
            self.assertIsNone(self.shell.route('mycelia population create colony --goal "edge ai operations" --seed analyst,reviewer --target-size 2').error)
            self.assertIsNone(self.shell.route('mycelia population tick colony --input "edge ai trend shift" --cycles 2').error)
            self.assertIsNone(self.shell.route("mycelia breed colony --count 1").error)
            select = self.shell.route("mycelia select colony --keep 1")
            lineage = self.shell.route("mycelia lineage colony --limit 12")
            species = self.shell.route("mycelia species colony")

        self.assertIsNone(select.error)
        select_payload = json.loads(select.output)
        self.assertTrue(select_payload["kept"])
        self.assertGreaterEqual(len(select_payload["kept"]), 1)

        self.assertIsNone(lineage.error)
        lineage_payload = json.loads(lineage.output)
        self.assertTrue(any(item["action"] == "member_bred" for item in lineage_payload))
        self.assertTrue(any(item["action"] in {"member_archived", "population_tick"} for item in lineage_payload))

        self.assertIsNone(species.error)
        species_payload = json.loads(species.output)
        self.assertTrue(species_payload)
        self.assertTrue(any(item["active_members"] >= 1 for item in species_payload))

    def test_mycelia_population_tick_swarm_routes_member_over_mesh(self) -> None:
        remote_calls: list[tuple[str, str]] = []

        def fake_remote(worker_url: str, command: str) -> CommandResult:
            remote_calls.append((worker_url, command))
            if command.startswith("agent create"):
                return CommandResult(output="created\n", data={"ok": True}, data_type=PipelineType.OBJECT)
            return CommandResult(output="swarm-analysis\n", data={"text": "swarm-analysis"}, data_type=PipelineType.OBJECT)

        self.assertIsNone(self.shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model analyst-model').error)
        self.assertIsNone(self.shell.route('mycelia population create colony --goal "gpu transformer edge ai" --seed analyst --target-size 2').error)
        self.shell.mesh.add_worker("http://worker-a", {"cpu", "py", "ai", "gpu"})
        with patch.object(self.shell.remote, "execute", side_effect=fake_remote):
            member = self.shell.mycelia.members_for_population("colony", active_only=True)[0]
            member.genome.traits["swarm_affinity"] = 0.95
            self.shell.mycelia._save_state()
            tick = self.shell.route('mycelia population tick colony --input "gpu transformer edge ai" --cycles 1 --swarm')

        self.assertIsNone(tick.error)
        payload = json.loads(tick.output)
        assignments = payload["cycles"][0]["assignments"]
        self.assertTrue(remote_calls)
        self.assertTrue(any(item["mode"] == "mesh" for item in assignments))

    def test_mycelia_population_persists_across_shell_sessions(self) -> None:
        first_shell: NovaShell | None = None
        second_shell: NovaShell | None = None
        try:
            first_shell = NovaShell()
            with patch.object(
                first_shell.ai_runtime,
                "complete_prompt",
                return_value=CommandResult(output="analysis\n", data={"text": "analysis"}, data_type=PipelineType.OBJECT),
            ):
                self.assertIsNone(first_shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model local-model').error)
                self.assertIsNone(first_shell.route('mycelia population create colony --goal "persistent edge ai colony" --seed analyst --target-size 2').error)
                self.assertIsNone(first_shell.route('mycelia population tick colony --input "persistent edge ai signal" --cycles 1').error)
        finally:
            if first_shell is not None:
                first_shell._close_loop()

        try:
            second_shell = NovaShell()
            listing = second_shell.route("mycelia population list")
            snapshot = second_shell.route("mycelia population show colony")
        finally:
            if second_shell is not None:
                second_shell._close_loop()

        self.assertIsNone(listing.error)
        listing_payload = json.loads(listing.output)
        self.assertTrue(any(item["name"] == "colony" for item in listing_payload))
        self.assertIsNone(snapshot.error)
        snapshot_payload = json.loads(snapshot.output)
        self.assertEqual(snapshot_payload["population"]["name"], "colony")
        self.assertTrue(snapshot_payload["members"])

    def test_mycelia_coevolve_run_records_curvature_and_forecast_metrics(self) -> None:
        daemon_runtime = self.shell.atheria.storage_root / "daemon_runtime"
        daemon_runtime.mkdir(parents=True, exist_ok=True)
        report_file = daemon_runtime / "atheria_daemon_audit.jsonl"
        rows = []
        for index in range(14):
            rows.append(
                {
                    "timestamp": float(index),
                    "reason": "population_tick",
                    "market": {
                        "trauma_pressure": 0.18 + (index * 0.01),
                        "last_signal_strength": 0.22 + (index * 0.015),
                        "samples_ingested": 12 + index,
                        "last_packet_quality": 0.82,
                        "last_market_snapshot": {"symbols": {}},
                    },
                    "dashboard": {
                        "system_temperature": 48.0 + index,
                        "entropic_index": 0.28 + (index * 0.01),
                        "structural_tension": 0.24 + (index * 0.02),
                        "market_guardian_score": 0.64,
                        "resource_pool": 18 + index,
                        "selection_pressure": 0.41,
                        "holographic_energy": 0.33,
                    },
                }
            )
        report_file.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

        def fake_complete(prompt: str, *, provider: str | None = None, model: str | None = None, system_prompt: str = "") -> CommandResult:
            return CommandResult(output="edge ai analysis with evidence\n", data={"text": "analysis"}, data_type=PipelineType.OBJECT)

        with patch.object(self.shell.ai_runtime, "complete_prompt", side_effect=fake_complete):
            self.assertIsNone(self.shell.route('agent create analyst "Analyze {{input}}" --provider lmstudio --model local-model').error)
            self.assertIsNone(self.shell.route('mycelia population create colony --goal "edge ai operations report" --seed analyst --target-size 2').error)
            result = self.shell.route(f'mycelia coevolve run colony --input "edge ai operations report" --cycles 1 --report-file {report_file}')

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertIn("coevolution", payload)
        metrics = payload["cycles"][0]["evaluations"][0]["metrics"]
        self.assertIn("forecast_alignment", metrics)
        self.assertIn("curvature_penalty", metrics)
        self.assertIn("tool_integrity", metrics)

        status = self.shell.route("mycelia coevolve status colony")
        self.assertIsNone(status.error)
        status_payload = json.loads(status.output)
        self.assertGreaterEqual(status_payload["run_count"], 1)

    def test_agent_run_lmstudio_timeout_returns_local_provider_hint(self) -> None:
        with patch("nova_shell.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            create = self.shell.route('agent create helper "Summarize {{input}}" --provider lmstudio --model local-model')
            self.assertIsNone(create.error)
            run = self.shell.route("agent run helper quarterly report")

        self.assertIsNotNone(run.error)
        self.assertIn("local model may still be loading", run.error)
        self.assertIn("LM_STUDIO_TIMEOUT", run.error)

    def test_event_on_emit_and_history(self) -> None:
        sub = self.shell.route("event on local_event 'py _.upper()'")
        self.assertIsNone(sub.error)

        emitted = self.shell.route("event emit local_event hello nova")
        self.assertIsNone(emitted.error)
        payload = json.loads(emitted.output)
        self.assertEqual(payload["executed"][0]["output"], "HELLO NOVA")

        history = self.shell.route("event history 1")
        self.assertIsNone(history.error)
        history_payload = json.loads(history.output)
        self.assertTrue(any(str(entry["stage"]).startswith("event local_event") for entry in history_payload))

    def test_gpu_graph_plan_and_run(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_run_kernel(kernel_file: str, pipeline_input: str = "") -> CommandResult:
            calls.append((kernel_file, pipeline_input))
            if len(calls) == 1:
                return CommandResult(output="2 4 6\n", data=[2.0, 4.0, 6.0], data_type=PipelineType.ARRAY_STREAM)
            return CommandResult(output="4 8 12\n", data=[4.0, 8.0, 12.0], data_type=PipelineType.ARRAY_STREAM)

        with patch.object(self.shell.gpu, "run_kernel", side_effect=fake_run_kernel):
            plan = self.shell.route('gpu graph plan first.cl second.cl --input "1 2 3"')
            self.assertIsNone(plan.error)
            plan_payload = json.loads(plan.output)
            self.assertEqual(len(plan_payload["kernels"]), 2)

            run = self.shell.route('gpu graph run first.cl second.cl --input "1 2 3"')
            self.assertIsNone(run.error)
            run_payload = json.loads(run.output)
            self.assertEqual(run_payload["output"].strip(), "4 8 12")

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], "1 2 3")
        self.assertEqual(calls[1][1], "2 4 6")

    def test_cpp_sandbox_reports_missing_emcc_or_usage(self) -> None:
        result = self.shell.route("cpp.sandbox 1 + 1")
        if result.error:
            self.assertIn("emcc", result.error)
        else:
            self.assertTrue(result.output.strip())


    def test_optimizer_suggest_and_run(self) -> None:
        suggest = self.shell.route("opt suggest matrix_mul 1+2")
        self.assertIsNone(suggest.error)
        payload = json.loads(suggest.output)
        self.assertIn("engine", payload)

        run = self.shell.route("opt run matrix_mul 1+2")
        self.assertIsNone(run.error)
        run_payload = json.loads(run.output)
        self.assertIn("delegated_command", run_payload)

    def test_reactive_file_trigger_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.shell.route(f"reactive on-file '{tmp}/*.txt' 'py _.endswith(\".txt\")'")
            self.assertIsNone(result.error)
            trigger = json.loads(result.output)
            listed = self.shell.route("reactive list")
            self.assertIsNone(listed.error)
            entries = json.loads(listed.output)
            self.assertTrue(any(item["id"] == trigger["id"] for item in entries))
            stop = self.shell.route(f"reactive stop {trigger['id']}")
            self.assertIsNone(stop.error)

    def test_rag_ingest_embeds_chunks_into_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "notes.md"
            doc.write_text(
                "Nova-shell coordinates tools and agents.\n\n"
                "Auto-RAG should watch incoming knowledge and index it immediately.\n",
                encoding="utf-8",
            )
            ingest = self.shell.route(
                f"rag ingest --file {doc} --namespace docs --project ingest --no-summary --no-atheria"
            )
            self.assertIsNone(ingest.error)
            payload = json.loads(ingest.output)
            self.assertGreaterEqual(payload["chunks"], 1)

            search = self.shell.route("memory search --namespace docs --project ingest incoming knowledge")
            self.assertIsNone(search.error)
            hits = json.loads(search.output)
            self.assertTrue(any("Auto-RAG" in hit["text"] for hit in hits))

    def test_rag_watch_ingests_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            watch = self.shell.route(
                f"rag watch '{tmp}/*.md' --namespace incoming --project watcher --no-summary --no-atheria"
            )
            self.assertIsNone(watch.error)
            watch_payload = json.loads(watch.output)
            try:
                doc = Path(tmp) / "new.md"
                doc.write_text("Watcher ingests fresh markdown into Nova-shell memory.\n", encoding="utf-8")
                deadline = time.time() + 2.0
                found = False
                while time.time() < deadline:
                    search = self.shell.route("memory search --namespace incoming --project watcher fresh markdown")
                    hits = json.loads(search.output) if search.error is None else []
                    if hits:
                        found = True
                        break
                    time.sleep(0.1)
                self.assertTrue(found)
            finally:
                stop = self.shell.route(f"rag stop {watch_payload['id']}")
                self.assertIsNone(stop.error)

    def test_guard_ebpf_status(self) -> None:
        result = self.shell.route("guard ebpf-status")
        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertIn("available", payload)

    def test_guard_list_includes_builtin_ebpf_profiles(self) -> None:
        result = self.shell.route("guard list")
        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertIn("ebpf_builtin", payload)
        self.assertIn("strict-ebpf", payload["ebpf_builtin"])

    def test_novascript_contract_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "typed.ns"
            script.write_text("rows: object_stream = data load missing.csv\n", encoding="utf-8")
            check = self.shell.route(f"ns.check {script}")
            self.assertIsNone(check.error)
            payload = json.loads(check.output)
            self.assertGreaterEqual(payload["contracts"], 1)

    def test_fabric_rdma_put_missing_file(self) -> None:
        result = self.shell.route("fabric rdma-put http://127.0.0.1:8765 /no/file")
        self.assertIsNotNone(result.error)
        self.assertIn("file not found", result.error)


    def test_graph_aot_fuses_cpp_expr_stages(self) -> None:
        result = self.shell.route("graph aot \"printf '1\\n2\\n' | cpp.expr x+1 | cpp.expr x*2\"")
        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertGreaterEqual(payload["fused_cpp_count"], 1)
        self.assertTrue(any(stage.startswith("cpp.expr_chain") for stage in payload["optimized_stages"]))

    def test_cpp_chain_template_escapes_newline_for_cpp(self) -> None:
        code = self.shell.novagraph._build_cpp_chain("x+1 ; x*2")
        self.assertIn('std::cout << x << "\\n";', code)
        self.assertNotIn("std::cout << x << '\n';", code)

    def test_graph_run_executes_fused_pipeline(self) -> None:
        result = self.shell.route("graph run \"printf '1\\n2\\n' | cpp.expr x+1 | cpp.expr x*2\"")
        if result.error is None:
            payload = json.loads(result.output)
            self.assertIn("output", payload)
        else:
            self.assertTrue("stod" in result.error or "g++" in result.error or result.error)

    def test_cpp_engine_injects_toolchain_bin_into_subprocess_path(self) -> None:
        engine = CppEngine()
        calls: list[dict[str, object]] = []

        def fake_run(_cmd: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="6\n", stderr="")

        compiler_path = r"C:\msys64\ucrt64\bin\g++.exe"
        with patch("nova_shell.resolve_gxx_command", return_value=compiler_path), patch("nova_shell.subprocess.run", side_effect=fake_run):
            result = engine.compile_and_run("int main(){return 0;}", "input")

        self.assertIsNone(result.error)
        self.assertEqual(result.output, "6\n")
        self.assertEqual(len(calls), 2)
        expected_dir = str(Path(compiler_path).resolve().parent)
        for kwargs in calls:
            env = kwargs.get("env")
            self.assertIsInstance(env, dict)
            path_value = str(env.get("PATH", ""))
            self.assertIn(expected_dir, [entry for entry in path_value.split(os.pathsep) if entry])

    def test_lens_replay_returns_snapshot_output(self) -> None:
        self.shell.route("py 10 + 1")
        last = self.shell.route("lens last")
        self.assertIsNone(last.error)
        snapshot = json.loads(last.output)
        replay = self.shell.route(f"lens replay {snapshot['id']}")
        self.assertIsNone(replay.error)

    def test_lens_fork_creates_diff_and_simulation(self) -> None:
        self.assertIsNone(self.shell.route('py {"trauma_pressure": 0.9, "network_latency": 12.0}').error)
        snapshot = json.loads(self.shell.route("lens last").output)
        with patch.object(self.shell, "_simulate_fork_payload", return_value={"mode": "mock-sim", "delta": 1}):
            fork = self.shell.route(f'lens fork {snapshot["id"]} --inject \'{{"trauma_pressure": 0.1}}\'')
        self.assertIsNone(fork.error)
        payload = json.loads(fork.output)
        self.assertEqual(payload["simulation"]["mode"], "mock-sim")
        self.assertTrue(any(row["path"] == "$.trauma_pressure" for row in payload["diff"]))

        diff = self.shell.route(f'lens diff {payload["id"]}')
        self.assertIsNone(diff.error)
        diff_payload = json.loads(diff.output)
        self.assertEqual(diff_payload["id"], payload["id"])
        self.assertTrue(any(row["path"] == "$.trauma_pressure" for row in diff_payload["diff"]))

    def test_atheria_sensor_load_run_and_train(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.shell.atheria, "train_rows", return_value=1):
            plugin = Path(tmp) / "ops_sensor.py"
            plugin.write_text(
                "def analyze(payload):\n"
                "    return {\n"
                "        'summary': 'ops event',\n"
                "        'features': {'system_temperature': 0.7},\n"
                "        'metadata': {'origin': 'test'}\n"
                "    }\n",
                encoding="utf-8",
            )
            mapping = Path(tmp) / "mapping.json"
            mapping.write_text(json.dumps({"cpu_usage": "$.system.cpu_usage", "network_latency": "$.system.latency"}), encoding="utf-8")

            load = self.shell.route(f"atheria sensor load {plugin} --name ops_sensor --mapping {mapping}")
            self.assertIsNone(load.error)

            run = self.shell.route(
                'atheria sensor run ops_sensor --input \'{"system":{"cpu_usage":0.91,"latency":18}}\' --train --namespace sensors --project ops'
            )

        self.assertIsNone(run.error)
        payload = json.loads(run.output)
        self.assertEqual(payload["name"], "ops_sensor")
        self.assertEqual(payload["features"]["cpu_usage"], 0.91)
        self.assertEqual(payload["features"]["network_latency"], 18.0)
        self.assertEqual(payload["trained_records"], 1)
        self.assertTrue(payload["memory_id"].startswith("mem_") or payload["memory_id"])

    def test_atheria_sensor_gallery_and_spawn_template(self) -> None:
        gallery = self.shell.route("atheria sensor gallery")
        self.assertIsNone(gallery.error)
        templates = json.loads(gallery.output)
        self.assertTrue(any(item["template"] == "RSS_Base" for item in templates))

        spawned = self.shell.route("atheria sensor spawn quantencomputing --template RSS_Base --name quantum_watch --anchor cpu")
        self.assertIsNone(spawned.error)
        payload = json.loads(spawned.output)
        self.assertEqual(payload["name"], "quantum_watch")
        self.assertEqual(payload["template"], "RSS_Base")
        self.assertEqual(payload["category"], "quantencomputing")
        self.assertTrue(payload["fold_signature"].startswith("fold_"))

        listed = self.shell.route("atheria sensor list")
        self.assertIsNone(listed.error)
        sensors = json.loads(listed.output)
        match = next(item for item in sensors if item["name"] == "quantum_watch")
        self.assertEqual(match["hardware_anchor"], "cpu")

    def test_atheria_guardian_status_and_prune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "ops_sensor.py"
            plugin.write_text(
                "def analyze(payload):\n"
                "    return {\n"
                "        'summary': 'ops event',\n"
                "        'features': {'resource_pressure': 0.2},\n"
                "        'metadata': {'origin': 'test'}\n"
                "    }\n",
                encoding="utf-8",
            )
            loaded = self.shell.route(f"atheria sensor load {plugin} --name stale_sensor --category ops")
            self.assertIsNone(loaded.error)
            spec = self.shell.atheria_sensors.plugins["stale_sensor"]
            spec.failure_count = 3
            spec.success_count = 0
            self.shell.atheria_sensors._save_registry()

            status = self.shell.route("atheria guardian status")
            dry_run = self.shell.route("atheria guardian prune --dry-run")
            applied = self.shell.route("atheria guardian prune")

        self.assertIsNone(status.error)
        status_payload = json.loads(status.output)
        self.assertTrue(any(item["name"] == "stale_sensor" for item in status_payload["prune_candidates"]))

        self.assertIsNone(dry_run.error)
        dry_run_payload = json.loads(dry_run.output)
        self.assertIn("stale_sensor", dry_run_payload["candidates"])

        self.assertIsNone(applied.error)
        applied_payload = json.loads(applied.output)
        self.assertIn("stale_sensor", applied_payload["pruned"])
        self.assertNotIn("stale_sensor", self.shell.atheria_sensors.plugins)

    def test_atheria_guardian_policy_set_and_list(self) -> None:
        listed = self.shell.route("atheria guardian policy list")
        self.assertIsNone(listed.error)
        policies = json.loads(listed.output)
        self.assertTrue(any(item["category"] == "default" for item in policies))

        updated = self.shell.route('atheria guardian policy set edge_ai {"desired_count":2,"auto_spawn":true,"template":"RSS_Base","hardware_anchor":"cpu","proximity_threshold":0.61}')
        self.assertIsNone(updated.error)
        payload = json.loads(updated.output)
        self.assertEqual(payload["category"], "edge_ai")
        self.assertEqual(payload["desired_count"], 2)
        self.assertAlmostEqual(float(payload["proximity_threshold"]), 0.61, places=2)

    def test_atheria_guardian_recommend_and_spawn_recommended(self) -> None:
        report_payload = json.dumps(
            {
                "summary": "Edge AI and local inference momentum are rising with infrastructure pressure.",
                "metadata": {
                    "forecast_direction": "emerging_uptrend",
                    "forecast_score": 0.83,
                    "confidence": 0.7,
                    "items": [
                        {"title": "Edge AI rollout expands"},
                        {"title": "Local inference startup funding rises"},
                        {"title": "Data center power demand increases"},
                    ],
                },
                "features": {
                    "signal_strength": 0.82,
                    "resource_pressure": 0.76,
                    "entropic_index": 0.41,
                    "queue_depth": 0.58,
                    "anomaly_score": 0.2,
                },
            },
            ensure_ascii=False,
        )
        recommend = self.shell.route(f"atheria guardian recommend --input '{report_payload}'")
        self.assertIsNone(recommend.error)
        recommend_payload = json.loads(recommend.output)
        self.assertTrue(any(item["category"] in {"edge_ai", "local_inference", "datacenter_scale"} for item in recommend_payload["spawn_recommendations"]))

        spawned = self.shell.route(f"atheria guardian spawn-recommended --input '{report_payload}' --limit 2")
        self.assertIsNone(spawned.error)
        spawned_payload = json.loads(spawned.output)
        self.assertLessEqual(len(spawned_payload["spawned"]), 2)
        for item in spawned_payload["spawned"]:
            self.assertTrue(item["lineage_parent"].startswith("guardian"))

    def test_atheria_sensor_run_emits_proximity_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "ops_sensor.py"
            plugin.write_text(
                "def analyze(payload):\n"
                "    return {\n"
                "        'summary': 'edge inference latency increase',\n"
                "        'features': {'signal_strength': 0.8, 'resource_pressure': 0.3},\n"
                "        'metadata': {'origin': 'test'}\n"
                "    }\n",
                encoding="utf-8",
            )
            load_a = self.shell.route(f"atheria sensor load {plugin} --name edge_watch --category edge_ai --tags edge,inference")
            load_b = self.shell.route(f"atheria sensor load {plugin} --name local_watch --category local_inference --tags inference,private")
            self.assertIsNone(load_a.error)
            self.assertIsNone(load_b.error)

            result = self.shell.route("atheria sensor run edge_watch --input '{}'")

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertIn("proximity_routes", payload)
        self.assertTrue(any(item["target"] == "local_watch" for item in payload["proximity_routes"]))

    def test_atheria_trend_rss_sensor_learns_baseline_and_forecast(self) -> None:
        sensor_path = (Path.cwd() / "trend_rss_sensor.py").resolve()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"INDUSTRY_TREND_STATE": str(Path(tmp) / "trend_state.json")}, clear=False):
            load = self.shell.route(f"atheria sensor load {sensor_path} --name trend_radar")
            self.assertIsNone(load.error)

            first_payload = json.dumps(
                [
                    {
                        "title": "AI runtime update",
                        "summary": "new agent workflow runtime release",
                        "source": "feed-a",
                        "url": "https://a",
                    },
                    {
                        "title": "Inference benchmark",
                        "summary": "research benchmark for model inference",
                        "source": "feed-b",
                        "url": "https://b",
                    },
                ]
            )
            first = self.shell.route(f"atheria sensor run trend_radar --input '{first_payload}'")
            self.assertIsNone(first.error)
            first_result = json.loads(first.output)
            self.assertEqual(first_result["metadata"]["history_length"], 1)
            self.assertEqual(first_result["metadata"]["forecast_direction"], "warming_baseline")

            second_payload = json.dumps(
                [
                    {
                        "title": "AI data center boom",
                        "summary": "massive gpu cluster power cooling expansion",
                        "source": "feed-a",
                        "url": "https://1",
                    },
                    {
                        "title": "GPU shortage risk",
                        "summary": "chip capacity bottleneck export control risk",
                        "source": "feed-b",
                        "url": "https://2",
                    },
                    {
                        "title": "Agent runtime funding",
                        "summary": "workflow planner runtime startup raises billion investment",
                        "source": "feed-c",
                        "url": "https://3",
                    },
                    {
                        "title": "Cloud latency pressure",
                        "summary": "deployment scale latency network region constraints",
                        "source": "feed-d",
                        "url": "https://4",
                    },
                ]
            )
            second = self.shell.route(f"atheria sensor run trend_radar --input '{second_payload}'")
            self.assertIsNone(second.error)
            second_result = json.loads(second.output)
            self.assertEqual(second_result["metadata"]["history_length"], 2)
            self.assertEqual(second_result["metadata"]["forecast_direction"], "emerging_uptrend")
            self.assertGreater(float(second_result["metadata"]["forecast_score"]), 0.7)
            self.assertEqual(len(second_result["metadata"]["items"]), 4)

    def test_atheria_evolve_simulate_from_text_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("nova_shell.Path.home", return_value=Path(tmp)):
            report = Path(tmp) / "trend_report.txt"
            report.write_text(
                "Direction: emerging_uptrend\n"
                "Forecast score: 0.82\n"
                "Confidence: 0.64\n"
                "Summary: Edge AI, data center power and GPU runtime demand are all rising.\n"
                "- AI data center boom | feed-a | https://a\n"
                "- Edge AI devices expand | feed-b | https://b\n"
                "- GPU runtime pressure increases | feed-c | https://c\n",
                encoding="utf-8",
            )
            shell = NovaShell()
            try:
                result = shell.route(f"atheria evolve simulate --file {report}")
            finally:
                shell._close_loop()

        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["mode"], "simulate")
        self.assertEqual(payload["plan"]["source"]["kind"], "text_report")
        self.assertGreater(float(payload["projected_state"]["active_policy"]["datacenter_scale"]), 0.5)

    def test_atheria_evolve_plan_apply_and_status_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("nova_shell.Path.home", return_value=Path(tmp)):
            shell = NovaShell()
            try:
                report_payload = json.dumps(
                    {
                        "summary": "Edge AI and local inference momentum are rising with infrastructure pressure.",
                        "metadata": {
                            "forecast_direction": "emerging_uptrend",
                            "forecast_score": 0.79,
                            "confidence": 0.67,
                            "items": [
                                {"title": "Edge AI rollout expands"},
                                {"title": "Local inference startup funding rises"},
                                {"title": "Data center power demand increases"},
                            ],
                        },
                        "features": {
                            "signal_strength": 0.8,
                            "resource_pressure": 0.74,
                            "entropic_index": 0.38,
                            "queue_depth": 0.57,
                            "anomaly_score": 0.2,
                        },
                    },
                    ensure_ascii=False,
                )
                planned = shell.route(f"atheria evolve plan --input '{report_payload}'")
                applied = shell.route("atheria evolve apply --reason 'align to market trend'")
                status = shell.route("atheria evolve status")
            finally:
                shell._close_loop()

        self.assertIsNone(planned.error)
        self.assertIsNone(applied.error)
        self.assertIsNone(status.error)
        planned_payload = json.loads(planned.output)
        applied_payload = json.loads(applied.output)
        status_payload = json.loads(status.output)
        self.assertEqual(planned_payload["kind"], "atheria_evolution_plan")
        self.assertEqual(applied_payload["mode"], "apply")
        self.assertTrue(status_payload["history"])
        self.assertEqual(status_payload["last_plan"]["kind"], "atheria_evolution_plan")

    def test_mesh_heartbeat_and_intelligent_run_no_worker(self) -> None:
        add = self.shell.route("mesh add http://127.0.0.1:9998 cpu")
        self.assertIsNone(add.error)
        beat = self.shell.route("mesh beat http://127.0.0.1:9998 3.5 handleA,handleB")
        self.assertIsNone(beat.error)
        run = self.shell.route("mesh intelligent-run gpu py 1+1 --handle handleA")
        self.assertIsNotNone(run.error)

    def test_mesh_start_worker_run_and_stop(self) -> None:
        started = self.shell.route("mesh start-worker --caps cpu,py")
        self.assertIsNone(started.error)
        payload = json.loads(started.output)
        worker_id = payload["worker_id"]
        worker_url = payload["url"]

        try:
            self.assertTrue(Path(payload["log_path"]).exists())
            listed = self.shell.route("mesh list")
            self.assertIsNone(listed.error)
            workers = json.loads(listed.output)
            match = next(worker for worker in workers if worker["url"] == worker_url)
            self.assertTrue(match["managed_local"])
            self.assertEqual(match["worker_id"], worker_id)
            self.assertIn("py", match["caps"])

            run = self.shell.route("mesh run py py 1 + 1")
            self.assertIsNone(run.error)
            self.assertEqual(run.output.strip(), "2")
        finally:
            stop = self.shell.route(f"mesh stop-worker {worker_id}")
            self.assertIsNone(stop.error)
            self.assertEqual(stop.output.strip(), "stopped")

        listed_after = self.shell.route("mesh list")
        self.assertIsNone(listed_after.error)
        self.assertFalse(any(worker.get("worker_id") == worker_id for worker in json.loads(listed_after.output)))

    def test_guard_ebpf_compile_and_enforce_blocks_term(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "guard.json"
            policy.write_text(json.dumps({
                "name": "strict-ebpf",
                "ebpf_enforce": True,
                "blocked_terms": ["curl"],
                "block_commands": []
            }), encoding="utf-8")
            load = self.shell.route(f"guard load {policy}")
            self.assertIsNone(load.error)
            compile_result = self.shell.route("guard ebpf-compile strict-ebpf")
            self.assertIsNone(compile_result.error)
            enforce = self.shell.route("guard ebpf-enforce strict-ebpf")
            self.assertIsNone(enforce.error)
            blocked = self.shell.route("sys curl http://example.com")
            self.assertIsNotNone(blocked.error)
            self.assertIn("blocked term", blocked.error)
            self.shell.route("guard ebpf-release")

    def test_guard_ebpf_compile_and_enforce_builtin_profile(self) -> None:
        compile_result = self.shell.route("guard ebpf-compile strict-ebpf")
        self.assertIsNone(compile_result.error)
        compile_payload = json.loads(compile_result.output)
        self.assertEqual(compile_payload["policy"], "strict-ebpf")

        enforce = self.shell.route("guard ebpf-enforce strict-ebpf")
        self.assertIsNone(enforce.error)
        enforce_payload = json.loads(enforce.output)
        self.assertEqual(enforce_payload["policy"], "strict-ebpf")

        blocked = self.shell.route("sys curl http://example.com")
        self.assertIsNotNone(blocked.error)
        self.assertIn("blocked term", blocked.error)
        self.shell.route("guard ebpf-release")

    def test_guard_ebpf_compile_and_enforce_from_relative_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            policy = tmp_path / "strict-local.json"
            policy.write_text(json.dumps({
                "name": "strict-local",
                "ebpf_enforce": True,
                "blocked_terms": ["curl"],
                "block_commands": [],
            }), encoding="utf-8")
            self.shell.cwd = tmp_path

            compile_result = self.shell.route("guard ebpf-compile strict-local.json")
            self.assertIsNone(compile_result.error)
            compile_payload = json.loads(compile_result.output)
            self.assertEqual(compile_payload["policy"], "strict-local")

            enforce = self.shell.route("guard ebpf-enforce strict-local.json")
            self.assertIsNone(enforce.error)
            enforce_payload = json.loads(enforce.output)
            self.assertEqual(enforce_payload["policy"], "strict-local")

            blocked = self.shell.route("sys curl http://example.com")
            self.assertIsNotNone(blocked.error)
            self.assertIn("blocked term", blocked.error)
            self.shell.route("guard ebpf-release")

    def test_novascript_watch_hook_and_emit(self) -> None:
        script = 'watch signal:\n    py "hook:" + $signal'
        exec_result = self.shell.route(f"ns.exec {script}")
        self.assertIsNone(exec_result.error)
        emitted = self.shell.route("ns.emit signal ping")
        self.assertIsNone(emitted.error)
        self.assertIn("hook:ping", emitted.output)


    def test_zero_pool_put_list_get_release(self) -> None:
        put = self.shell.route("zero put hello-zero")
        self.assertIsNone(put.error)
        payload = json.loads(put.output)
        handle = payload["handle"]

        listed = self.shell.route("zero list")
        self.assertIsNone(listed.error)
        rows = json.loads(listed.output)
        self.assertTrue(any(r["handle"] == handle for r in rows))

        got = self.shell.route(f"zero get {handle}")
        self.assertIsNone(got.error)
        self.assertIn("hello-zero", got.output)

        rel = self.shell.route(f"zero release {handle}")
        self.assertIsNone(rel.error)
        self.assertEqual(rel.output.strip(), "released")
        listed_after = self.shell.route("zero list")
        self.assertFalse(any(row["handle"] == handle for row in json.loads(listed_after.output)))

    def test_blob_pack_verify_unpack_roundtrip_for_ns_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hello.ns"
            blob_file = Path(tmp) / "hello.nsblob.json"
            restored = Path(tmp) / "restored.ns"
            source.write_text('py "blob-ok"\n', encoding="utf-8")

            packed = self.shell.route(f"blob pack {source} --output {blob_file}")
            self.assertIsNone(packed.error)
            packed_payload = json.loads(packed.output)
            self.assertTrue(blob_file.exists())
            self.assertTrue(packed_payload["verified"])
            self.assertEqual(packed_payload["blob"]["kind"], "ns")

            verified = self.shell.route(f"blob verify {blob_file}")
            self.assertIsNone(verified.error)
            self.assertTrue(json.loads(verified.output)["verified"])

            executed = self.shell.route(f"blob exec {blob_file}")
            self.assertIsNone(executed.error)
            self.assertIn("blob-ok", executed.output)

            unpacked = self.shell.route(f"blob unpack {blob_file} --output {restored}")
            self.assertIsNone(unpacked.error)
            self.assertEqual(restored.read_text(encoding="utf-8"), 'py "blob-ok"\n')

    def test_blob_exec_inline_runs_python_payload(self) -> None:
        packed = self.shell.route('blob pack --text "21 * 2" --type py')
        self.assertIsNone(packed.error)
        packed_payload = json.loads(packed.output)
        inline_seed = packed_payload["inline_seed"]

        executed = self.shell.route(f"blob exec-inline {inline_seed}")
        self.assertIsNone(executed.error)
        self.assertEqual(executed.output.strip(), "42")

    def test_blob_mesh_run_sends_inline_seed_to_remote_worker(self) -> None:
        packed = self.shell.route('blob pack --text "21 * 2" --type py')
        self.assertIsNone(packed.error)
        blob_path = json.loads(packed.output)["path"]

        self.shell.mesh.add_worker("http://127.0.0.1:9999", {"cpu"})
        with patch.object(self.shell.remote, "execute", return_value=CommandResult(output="42\n")) as execute_mock:
            ran = self.shell.route(f"blob mesh-run cpu {blob_path}")

        self.assertIsNone(ran.error)
        payload = json.loads(ran.output)
        self.assertEqual(payload["worker_url"], "http://127.0.0.1:9999")
        self.assertIn("blob exec-inline nsblob:", payload["command"])
        execute_mock.assert_called_once()

    def test_clear_and_cls_are_builtin_commands(self) -> None:
        with (
            patch("nova_shell.sys.stdout.isatty", return_value=True),
            patch("nova_shell.os.system", return_value=0) as system_mock,
        ):
            clear_result = self.shell.route("clear")
            cls_result = self.shell.route("cls")
        self.assertIsNone(clear_result.error)
        self.assertIsNone(cls_result.error)
        self.assertEqual(clear_result.output, "")
        self.assertEqual(cls_result.output, "")
        self.assertEqual(system_mock.call_count, 2)

    def test_synth_suggest_and_autotune(self) -> None:
        suggest = self.shell.route("synth suggest py 1 + 1")
        self.assertIsNone(suggest.error)
        payload = json.loads(suggest.output)
        self.assertIn("engine", payload)

        tuned = self.shell.route("synth autotune py 1 + 1")
        if tuned.error is None:
            self.assertIn("result", json.loads(tuned.output))
        else:
            self.assertTrue(tuned.error)

    def test_synth_forecast_and_predictive_shift_suggestion(self) -> None:
        dashboard = {
            "dashboard": {
                "system_temperature": 96.0,
                "structural_tension": 0.83,
                "market_guardian_score": 0.28,
            }
        }
        with patch.object(self.shell.atheria, "status_payload", return_value=dashboard):
            for value in range(10):
                result = self.shell.route(f"py {value} + 1")
                self.assertIsNone(result.error)

        forecast = self.shell.route("synth forecast")
        self.assertIsNone(forecast.error)
        forecast_payload = json.loads(forecast.output)
        self.assertEqual(forecast_payload["status"], "ok")
        self.assertIn("projection", forecast_payload)

        suggestion = self.shell.route('synth shift suggest "for item in rows: total += item"')
        self.assertIsNone(suggestion.error)
        suggestion_payload = json.loads(suggestion.output)
        self.assertIn(suggestion_payload["engine"], {"cpp", "mesh"})
        self.assertIn("delegated_command", suggestion_payload)
        self.assertIn("forecast", suggestion_payload)

    def test_mesh_federated_publish_apply_and_broadcast(self) -> None:
        put = self.shell.route("zero put federated-invariant-payload")
        self.assertIsNone(put.error)
        zero_payload = json.loads(put.output)
        handle = zero_payload["handle"]
        size = int(zero_payload["size"])

        published = self.shell.route(
            f'mesh federated publish --statement "Inter-core resonance raised" --namespace swarm --project lab --handle {handle} --size {size} --type text --same-host'
        )
        self.assertIsNone(published.error)
        published_payload = json.loads(published.output)
        applied = self.shell.federated.apply_update(published_payload, worker_node_id="worker-local")
        self.assertTrue(applied["verified"])
        self.assertTrue(applied["payload_integrity_ok"])
        self.assertTrue(applied["applied"])

        self.shell.mesh.add_worker("http://127.0.0.1:9999", {"ai", "cpu"})
        with patch("nova.mesh.federated.urllib.request.urlopen", return_value=FakeHTTPResponse({"applied": True, "verified": True})):
            broadcast = self.shell.route('mesh federated publish --statement "Shared invariant" --broadcast')
        self.assertIsNone(broadcast.error)
        broadcast_payload = json.loads(broadcast.output)
        self.assertEqual(broadcast_payload["broadcast"]["applied_count"], 1)

    def test_pulse_status_and_snapshot(self) -> None:
        self.shell.route("py 1 + 1")
        status = self.shell.route("pulse status")
        self.assertIsNone(status.error)
        payload = json.loads(status.output)
        self.assertIn("recent_event_count", payload)

        snap = self.shell.route("pulse snapshot")
        self.assertIsNone(snap.error)
        snap_payload = json.loads(snap.output)
        self.assertIn("events", snap_payload)

    def test_dflow_subscribe_publish_list(self) -> None:
        sub = self.shell.route("dflow subscribe test_event 'py _ + \"!\"'")
        self.assertIsNone(sub.error)
        listed = self.shell.route("dflow list")
        self.assertIsNone(listed.error)
        topics = json.loads(listed.output)
        self.assertIn("test_event", topics)

        pub = self.shell.route("dflow publish test_event ping")
        self.assertIsNone(pub.error)
        result = json.loads(pub.output)
        self.assertIn("executed", result)
        self.assertEqual(result["executed"][0]["error"], "")
        self.assertEqual(result["executed"][0]["output"], "ping!")

    def test_dflow_publish_supports_payload_with_spaces(self) -> None:
        self.shell.route("dflow subscribe test_event 'py _.upper()'")
        pub = self.shell.route("dflow publish test_event hello nova shell")
        self.assertIsNone(pub.error)
        result = json.loads(pub.output)
        self.assertEqual(result["executed"][0]["error"], "")
        self.assertEqual(result["executed"][0]["output"], "HELLO NOVA SHELL")

    def test_guard_sandbox_status_toggle(self) -> None:
        on = self.shell.route("guard sandbox on")
        self.assertIsNone(on.error)
        status = self.shell.route("guard sandbox status")
        self.assertIsNone(status.error)
        payload = json.loads(status.output)
        self.assertTrue(payload["sandbox_default"])
        off = self.shell.route("guard sandbox off")
        self.assertIsNone(off.error)


if __name__ == "__main__":
    unittest.main()
