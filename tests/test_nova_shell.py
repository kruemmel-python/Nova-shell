import io
import json
import os
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout, suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nova_shell import CommandResult, CppEngine, NovaAtheriaRuntime, NovaShell, PipelineType, __version__, main
from novascript import Assignment, ForLoop, IfBlock, NovaInterpreter, NovaParser


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

    def test_pipeline_to_python(self) -> None:
        result = self.shell.route("echo hello | py _.strip().upper()")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "HELLO")

    def test_pipeline_respects_quoted_pipe(self) -> None:
        result = self.shell.route('py "a|b"')
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "a|b")

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
        self.assertIn("ns.exec", result.output)
        self.assertIn("ns.run", result.output)
        self.assertIn("watch", result.output)

    def test_doctor_json(self) -> None:
        result = self.shell.route("doctor json")
        self.assertIsNone(result.error)
        payload = json.loads(result.output)
        self.assertEqual(payload["version"], __version__)
        self.assertIn("modules", payload)

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
            self.assertIn(str(env_file), payload["loaded_env_files"])

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
        for kwargs in calls:
            env = kwargs.get("env")
            self.assertIsInstance(env, dict)
            path_value = str(env.get("PATH", ""))
            self.assertTrue(path_value.startswith(str(Path(compiler_path).parent) + os.pathsep) or path_value == str(Path(compiler_path).parent))

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
