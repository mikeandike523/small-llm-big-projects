from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys  import Keys
from termcolor import colored


@dataclass(frozen=True)
class PromptOutcome:
    """
    submitted=True  -> user submitted via Ctrl+Enter / Alt+Enter
    submitted=False -> user aborted via Ctrl+C
    text            -> captured buffer contents
    """
    submitted: bool
    aborted: bool
    text: str


def multiline_prompt(
    prompt: str = "> ",
    *,
    print_controls: str = "before",  # "before" | "after" | "none"
    session: Optional[PromptSession] = None,
) -> PromptOutcome:
    """
    Multiline prompt behavior:

      Enter        -> newline (never submits)
      Ctrl+J or Alt+Enter   -> submit
      Ctrl+C       -> abort (returns captured text, does NOT exit program)

    Returns:
        PromptOutcome(submitted, aborted, text)
    """
    kb = KeyBindings()
    state = {"aborted": False}

    # Ctrl+C: abort, but capture buffer text.
    @kb.add("c-c")
    def _(event):
        state["aborted"] = True
        event.app.exit(result=event.app.current_buffer.text)

    # Enter: always newline (prevents accidental submit + helps with paste)
    @kb.add("enter")
    def _(event):
        event.app.current_buffer.insert_text("\n")

    # Ctrl+J: submit
    @kb.add("c-j")
    def _(event):
        event.app.exit(result=event.app.current_buffer.text)

    # Alt+Enter fallback (Escape + Enter)
    @kb.add("escape", "enter")
    def _(event):
        event.app.exit(result=event.app.current_buffer.text)

    controls_text = (
        "Controls: "
        "Enter → newline  •  "
        "Ctrl+J or Alt+Enter → submit  •  "

        "Ctrl+C → abort"
    )
    controls_blue = colored(controls_text, "blue")

    if print_controls == "before":
        print(controls_blue)

    sess = session or PromptSession(multiline=True, key_bindings=kb)
    text = sess.prompt(prompt)

    if print_controls == "after":
        print(controls_blue)

    if state["aborted"]:
        return PromptOutcome(submitted=False, aborted=True, text=text)

    return PromptOutcome(submitted=True, aborted=False, text=text)