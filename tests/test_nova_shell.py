import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from nova_shell import NovaShell, PipelineType
from novascript import Assignment, ForLoop, IfBlock, NovaInterpreter, NovaParser


class NovaShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_cwd = Path.cwd()
        self.shell = NovaShell()

    def tearDown(self) -> None:
        self.shell.route(f"cd {self.original_cwd}")

    def test_python_expression(self) -> None:
        result = self.shell.route("py 1 + 2")
        self.assertIsNone(result.error)
        self.assertEqual(result.output.strip(), "3")

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
        self.assertIn("data load", result.output)

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


if __name__ == "__main__":
    unittest.main()
