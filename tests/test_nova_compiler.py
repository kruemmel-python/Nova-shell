import unittest

from nova.compiler import NovaGraphBuilder, NovaValidator
from nova.parser import NovaParser


PROGRAM = """
agent researcher {
model: llama3
}

dataset tech_rss {
source: rss
}

flow radar {
rss.fetch tech_rss
researcher summarize tech_rss
}

event refresh {
on dataset.updated
do radar
}
"""


class NovaCompilerTests(unittest.TestCase):
    def test_validation_passes_for_valid_program(self) -> None:
        parser = NovaParser()
        validator = NovaValidator()
        result = validator.validate(parser.parse(PROGRAM))
        self.assertTrue(result.valid)

    def test_graph_builder_generates_plan(self) -> None:
        parser = NovaParser()
        builder = NovaGraphBuilder()
        _graph, plan = builder.build(parser.parse(PROGRAM))
        self.assertTrue(plan.order)
        self.assertTrue(any(node["id"] == "flow:radar" for node in plan.nodes))


if __name__ == "__main__":
    unittest.main()
