import json
import threading
import click
from termcolor import colored
import sys

from src.cli_obj import cli
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.cli.multiline_prompt import multiline_prompt
from src.utils.cli.slash_commands import try_handle_slash_command
from src.utils.llm.streaming import StreamingLLM
from src.tools import ALL_TOOL_DEFINITIONS, execute_tool
from src.logic.system_prompt import SYSTEM_PROMPT


def _run_with_spinner(fn):
    """Run fn() in a daemon thread while showing a \\r spinner. Returns its result."""
    done = threading.Event()
    holder, exc_holder = [], []

    def target():
        try:
            holder.append(fn())
        except Exception as e:
            exc_holder.append(e)
        finally:
            done.set()

    threading.Thread(target=target, daemon=True).start()
    frames = ['|', '/', '-', '\\']
    i = 0
    while not done.wait(0.1):
        sys.stdout.write(f'\rThinking... {frames[i % 4]}')
        sys.stdout.flush()
        i += 1
    sys.stdout.write('\r' + ' ' * 20 + '\r')
    sys.stdout.flush()

    if exc_holder:
        raise exc_holder[0]
    return holder[0]


@cli.command()
@click.option(
    '--streaming', default=True, type=bool, show_default=True,
    help='Stream tokens as they arrive. Set false to receive the full response at once (useful for diagnosing vLLM garbled-character bugs).',
)
def chat(streaming):
    """
    Start a chat with your model of choice.
    """

    # Step 1, get the token from the database

    pool = get_pool()

    token_value, endpoint_url = None, None

    with pool.get_connection() as conn:
        active_token = KVManager(conn).get_value("active_token")
        if not active_token:
            click.echo("No active token set. Use `token use <provider> [name]` first.")
            return

        provider = active_token["provider"]
        token_name = active_token.get("name", "")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token_value, endpoint_url
                FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, token_name),
            )
            row = cursor.fetchone()

        if not row:
            click.echo(f"Token not found for provider={provider!r}, name={token_name!r}.")
            return

        token_value, endpoint_url = row

    if not token_value:
        click.echo(colored("Could not retrieve token value","red"))
        raise SystemExit(-1)
    if not endpoint_url:
        click.echo(colored("Could not retrieve endpoint url value", "red"))
        raise SystemExit(-1)
    
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        model = kv.get_value("model") or None
        param_keys = kv.list_keys(prefix="params.")
        llm_params = {k[len("params."):]: kv.get_value(k) for k in param_keys}


    print(f"Endpoint url: {endpoint_url}")
    if token_name:
        print(f"Token name: {token_name}")
    print(f"Token value: {token_value[:2] + '...' + token_value[-2:]}")
    print(f"Model: {model or '(not set)'}")
    if llm_params:
        for k, v in llm_params.items():
            print(f"Param {k}: {v}")
    print(f"Streaming: {'enabled' if streaming else 'disabled'}")

    acc_data = {
        "reasoning":"",
        "content":""
    }

    def on_data(data):
        # Hot patch for an issue with Qwen3 parsing on openrouter
        # Where EOS token shows up in output
        if endpoint_url=="https://openrouter.ai/api/v1":
            data["content"].rstrip()
        content_previously_blank = not acc_data["content"]
        acc_data["reasoning"]+=data.get("reasoning") or ''
        acc_data["content"]+=data.get("content") or ''
        if data.get("reasoning"):
            sys.stdout.write(colored(data.get("reasoning"),"blue"))
            sys.stdout.flush()
        if data.get("content"):
            if content_previously_blank:
                sys.stdout.write("\n\n")
                sys.stdout.flush()
            sys.stdout.write(data.get("content"))
            sys.stdout.flush()
        

    

    streaming_llm = StreamingLLM(endpoint_url, token_value, 60, model, llm_params)
    
    ml_result = None

    message_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    session_data={}

    while ml_result is None or ml_result.submitted:

        ml_result = multiline_prompt()
        if ml_result.aborted:
            break

        user_input = ml_result.text
        slash_result = try_handle_slash_command(user_input, session_data)
        if slash_result.handled:
            click.echo(colored(slash_result.output, "cyan"))
            continue

        message_history.append({
            "role": "user",
            "content": user_input,
        })

        while True:
            acc_data["reasoning"] = ""
            acc_data["content"] = ""

            if streaming:
                try:
                    result = streaming_llm.stream(message_history, on_data, tools=ALL_TOOL_DEFINITIONS)
                except Exception:
                    raise SystemExit(-1)
            else:
                try:
                    result = _run_with_spinner(
                        lambda: streaming_llm.fetch(message_history, tools=ALL_TOOL_DEFINITIONS)
                    )
                except Exception:
                    raise SystemExit(-1)
                acc_data["reasoning"] = result.reasoning
                acc_data["content"] = result.content
                if result.reasoning:
                    sys.stdout.write(colored(result.reasoning, "blue"))
                    sys.stdout.flush()
                if result.content:
                    sys.stdout.write("\n\n" + result.content)
                    sys.stdout.flush()

            if result.has_tool_calls:
                message_history.append({
                    "role": "assistant",
                    "content": acc_data["content"] or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in result.tool_calls
                    ],
                })

                for tc in result.tool_calls:
                    sys.stdout.write(colored(f"\n[Tool call: {tc.name}  args={tc.arguments}]", "magenta"))
                    sys.stdout.flush()
                    tool_result = execute_tool(tc.name, tc.arguments, session_data)
                    sys.stdout.write(colored(f"\n[Tool result: {tool_result[:300]}{'...' if len(tool_result) > 300 else ''}]", "magenta"))
                    sys.stdout.flush()

                    message_history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })
                continue

            else:
                message_history.append({"role": "assistant", "content": acc_data["content"]})
                sys.stdout.write("\n\n")
                sys.stdout.flush()
                break


        
    
    click.echo("Bye!")
