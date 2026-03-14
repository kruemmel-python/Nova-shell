import unittest

from nova.ast import AgentDecl, MemoryDecl, SensorDecl
from nova.parser import NovaLexer, NovaParseError, NovaParser


PROGRAM = """
agent researcher {
model: llama3
}

sensor market_watch {
kind: rss
}

memory memory_bank {
backend: atheria
}
"""


class NovaParserTests(unittest.TestCase):
    def test_lexer_emits_header_tokens(self) -> None:
        lexer = NovaLexer()
        tokens = lexer.tokenize(PROGRAM)
        self.assertTrue(any(token.kind == "HEADER" for token in tokens))

    def test_parser_supports_sensor_and_memory(self) -> None:
        parser = NovaParser()
        program = parser.parse(PROGRAM)
        self.assertEqual(len(program.by_type(AgentDecl)), 1)
        self.assertEqual(len(program.by_type(SensorDecl)), 1)
        self.assertEqual(len(program.by_type(MemoryDecl)), 1)

    def test_parser_reports_missing_brace(self) -> None:
        parser = NovaParser()
        with self.assertRaises(NovaParseError):
            parser.parse("agent broken {\nmodel: llama3")


if __name__ == "__main__":
    unittest.main()
