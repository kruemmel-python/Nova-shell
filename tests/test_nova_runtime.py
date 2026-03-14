import unittest

from nova.runtime import RuntimeExecutor


PROGRAM = """
agent researcher {
model: llama3
}

flow radar {
researcher summarize headlines
emit dataset.updated headlines
}

event on_update {
on dataset.updated
do radar
}
"""


class NovaRuntimeTests(unittest.TestCase):
    def test_executor_returns_schedule_and_results(self) -> None:
        executor = RuntimeExecutor()
        result = executor.execute(PROGRAM, entry_flows=["radar"])

        self.assertTrue(result.schedule)
        self.assertIn("radar", result.flow_results)
        self.assertEqual(result.flow_results["radar"][0]["agent"], "researcher")


if __name__ == "__main__":
    unittest.main()
