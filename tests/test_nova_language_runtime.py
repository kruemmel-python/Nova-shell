import unittest

from nova.ast import AgentDecl, DatasetDecl, EventDecl, FlowDecl
from nova.graph import GraphCompiler
from nova.parser import NovaParseError, NovaParser
from nova.runtime import NovaRuntime


PROGRAM = """
agent researcher {
model: llama3
}

dataset tech_rss {
source: rss
}

flow radar {
```
rss.fetch tech_rss
researcher summarize tech_rss
emit dataset.updated tech_rss
```
}

event on_update {
on dataset.updated
do radar
}
"""


class NovaLanguageRuntimeTests(unittest.TestCase):
    def test_parser_generates_declarations(self) -> None:
        parser = NovaParser()
        program = parser.parse(PROGRAM)

        self.assertEqual(len(program.by_type(AgentDecl)), 1)
        self.assertEqual(len(program.by_type(DatasetDecl)), 1)
        self.assertEqual(len(program.by_type(FlowDecl)), 1)
        self.assertEqual(len(program.by_type(EventDecl)), 1)

    def test_parser_reports_structure_errors(self) -> None:
        parser = NovaParser()
        with self.assertRaises(NovaParseError):
            parser.parse("agent bad\nmodel: llama3\n}")

    def test_graph_compiler_builds_dag(self) -> None:
        parser = NovaParser()
        compiler = GraphCompiler()
        graph = compiler.compile(parser.parse(PROGRAM))

        self.assertIn("agent:researcher", graph.nodes)
        self.assertIn("flow:radar", graph.nodes)
        self.assertTrue(graph.topological_order())

    def test_runtime_executes_flow_and_emits_events(self) -> None:
        runtime = NovaRuntime()
        runtime.load(PROGRAM)
        outputs = runtime.run_flow("radar")

        self.assertEqual(len(outputs), 3)
        self.assertEqual(outputs[0]["mode"], "local")
        self.assertEqual(outputs[1]["agent"], "researcher")


if __name__ == "__main__":
    unittest.main()
