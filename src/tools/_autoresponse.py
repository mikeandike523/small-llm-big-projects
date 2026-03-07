from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AutoResponse:
    """
    A rule for automatically responding to an interactive CLI prompt.

    command_patterns:
        Ordered list of regexes matched positionally against [command, arg1, arg2, ...].
        May be shorter than the actual invocation (prefix/partial match is fine).
        Must never be longer than the actual invocation (rule cannot match if it
        demands more positional slots than exist in the real argv).
        Each regex is matched with re.search (not fullmatch), case-insensitive.

    output_pattern:
        Regex matched against the accumulated autoresponse buffer (all stdout since
        the last autoresponse was triggered). Case-insensitive re.search.

    response:
        String written verbatim to stdin when both patterns match.
        Include newline if the program expects Enter (e.g. "y\\n", "\\n").

    description:
        Human-readable label — for maintainers only, not used at runtime.
    """

    command_patterns: list[str]
    output_pattern: str
    response: str
    description: str = ""

    # Compiled patterns cached after first use
    _compiled_output: re.Pattern | None = field(default=None, init=False, repr=False)
    _compiled_commands: list[re.Pattern] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._compiled_output = re.compile(self.output_pattern, re.IGNORECASE)
        self._compiled_commands = [
            re.compile(p, re.IGNORECASE) for p in self.command_patterns
        ]

    def matches_command(self, argv: list[str]) -> bool:
        """
        argv = [command, arg1, arg2, ...]
        Returns True iff command_patterns is a valid positional prefix of argv.
        """
        if len(self._compiled_commands) > len(argv):
            return False
        return all(
            pat.search(arg)
            for pat, arg in zip(self._compiled_commands, argv)
        )

    def matches_output(self, text: str) -> bool:
        assert self._compiled_output is not None
        return bool(self._compiled_output.search(text))


# ---------------------------------------------------------------------------
# Rule manifest
#
# Edit this list to add or remove autoresponse rules.
# Order matters: the first rule whose command_patterns AND output_pattern both
# match is used; subsequent rules are not checked.
#
# command_patterns examples:
#   [r"^npx$"]                    matches any:  npx <anything>
#   [r"^npx$", r"create-react"]   matches only: npx create-react-app ...
#   [r"^npm$", r"^install$"]      matches only: npm install ...
# ---------------------------------------------------------------------------

KNOWN_AUTORESPONSES: list[AutoResponse] = [
    AutoResponse(
        description="npx: 'Need to install package — Ok to proceed?' -> y + Enter",
        command_patterns=[r"^npx$"],
        output_pattern=r"Ok to proceed",
        response="y\n",
    ),

    # Add more rules here as needed. Uncomment and adapt these examples:

    # AutoResponse(
    #     description="npm init: 'Is this OK?' -> y + Enter",
    #     command_patterns=[r"^npm$", r"^init$"],
    #     output_pattern=r"Is this OK\?",
    #     response="y\n",
    # ),

    # AutoResponse(
    #     description="pip install: 'Proceed? [y/N]' -> y + Enter",
    #     command_patterns=[r"^pip\d*$", r"^install$"],
    #     output_pattern=r"Proceed\?\s*\[y/N\]",
    #     response="y\n",
    # ),

    # AutoResponse(
    #     description="Any prompt ending with '(y)' or '[y/n]' -> Enter (accept default)",
    #     command_patterns=[],   # empty = matches any command
    #     output_pattern=r"\(y\)[\s]*$|\[y/n\][\s]*$",
    #     response="\n",
    # ),
]


def get_applicable_rules(argv: list[str]) -> list[AutoResponse]:
    """Return rules whose command_patterns match this argv (used to pre-filter)."""
    return [r for r in KNOWN_AUTORESPONSES if r.matches_command(argv)]


def find_response(text: str, rules: list[AutoResponse]) -> str | None:
    """
    Return the response string for the first rule whose output_pattern matches
    text, or None if no rule matches.
    """
    for rule in rules:
        if rule.matches_output(text):
            return rule.response
    return None
