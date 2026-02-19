import json
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


@cli.command()
def chat():
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
        model = KVManager(conn).get_value("model")
        if not model:
            model=None

    
    print(f"Endpoint url: {endpoint_url}")
    if token_name:
        print(f"Token name: {token_name}")
    print(f"Token value: {token_value[:2] + '...' + token_value[-2:]}")
    print(f"Model: {model or '(not set)'}")

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
        

    

    streaming_llm = StreamingLLM(endpoint_url, token_value, 60,model,{
        # "max_tokens": 8192
        # Actually, we should not provide a default value here
    })
    
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

            try:
                stream_result = streaming_llm.stream(message_history, on_data, tools=ALL_TOOL_DEFINITIONS)
            except Exception:
                raise SystemExit(-1)

            if stream_result.has_tool_calls:
                message_history.append({
                    "role": "assistant",
                    "content": acc_data["content"] or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in stream_result.tool_calls
                    ],
                })

                for tc in stream_result.tool_calls:
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
