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

from nova_shell import CommandResult, CppEngine, NovaShell, PipelineType, __version__, main
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
        self.shell = NovaShell()

    def tearDown(self) -> None:
        try:
            self.shell.route(f"cd {self.original_cwd}")
        finally:
            with suppress(Exception):
                self.shell._close_loop()

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
