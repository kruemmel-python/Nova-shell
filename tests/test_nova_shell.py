import unittest

from nova_shell import NovaShell


class NovaShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = NovaShell()

    def test_python_expression(self) -> None:
        result = self.shell.route("py 1 + 2")
        self.assertEqual(result.error, None)
        self.assertEqual(result.output.strip(), "3")

    def test_pipeline_to_python(self) -> None:
        result = self.shell.route("echo hello | py _.strip().upper()")
        self.assertEqual(result.error, None)
        self.assertEqual(result.output.strip(), "HELLO")

    def test_system_fallback(self) -> None:
        result = self.shell.route("echo ok")
        self.assertEqual(result.error, None)
        self.assertEqual(result.output.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
