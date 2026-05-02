import argparse
import json
import pathlib
import subprocess
import sys
import uuid
from time import sleep

from ddgs import DDGS
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

import todo
from agent import Agent

console = Console()

parser = argparse.ArgumentParser(description="nanoloop: agent CLI for small models")

parser.add_argument("-bb", "--big-model-base-url", type=str)
parser.add_argument("-sb", "--small-model-base-url", type=str)
parser.add_argument("-small", "--small-model-name", type=str)
parser.add_argument("-big", "--big-model-name", type=str)
parser.add_argument("-sa", "--small-api-key", type=str)
parser.add_argument("-ba", "--big-api-key", type=str)

args = parser.parse_args()

# ── Tool definitions ──────────────────────────────────────────────────────────

subagent_tools = [
    {
        "type": "function",
        "function": {
            "name": "shell_command",
            "description": "Execute a bash command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to run.",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file by replacing a unique string with a new string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "absolute_path": {"type": "string"},
                    "original_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["absolute_path", "original_string", "new_string"],
            },
        },
    },
]

big_agent_tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for up-to-date information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The specific question to answer.",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_command",
            "description": "Execute bash commands on the local system.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The full bash command to execute.",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": (
                "Delegate a self-contained task to a smaller LLM agent that has its own "
                "reasoning loop and can run shell commands and edit files. Use this for "
                "multi-step tasks like indexing a codebase, running test suites, or making "
                "a series of file edits. Returns the subagent's final answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "A clear, self-contained description of what the subagent must accomplish and what to return.",
                    }
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_todo",
            "description": "Add a new task to the todo list.",
            "parameters": {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_todo_complete",
            "description": "Mark a todo item as complete by its 1-based number.",
            "parameters": {
                "type": "object",
                "properties": {"task_number": {"type": "integer"}},
                "required": ["task_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_todo",
            "description": "Edit an existing todo's text by its 1-based number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_number": {"type": "integer"},
                    "updated_task": {"type": "string"},
                },
                "required": ["task_number", "updated_task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_todo",
            "description": "Clear all items from the todo list.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {"name": "view_todo", "description": "View the todo list."},
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file surgically by replacing a unique string with a new string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "absolute_path": {"type": "string"},
                    "original_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["absolute_path", "original_string", "new_string"],
            },
        },
    },
]

# ── Agents ────────────────────────────────────────────────────────────────────

big_agent = Agent(
    base_url=args.big_model_base_url,
    api_key=args.big_api_key,
    model=args.big_model_name,
    tools=big_agent_tools,
)

small_agent = Agent(
    base_url=args.small_model_base_url,
    api_key=args.small_api_key,
    model=args.small_model_name,
    tools=subagent_tools,
)

# ── Session setup ─────────────────────────────────────────────────────────────

cwd = pathlib.Path.cwd()

system_prompt = {
    "role": "system",
    "content": f"""
You are nanoloop, a lightweight AI agent running on a local LLM.
Act efficiently and correctly to complete the user's tasks.

ALWAYS use the todo list for planning.
Use spawn_subagent to delegate multi-step shell or file tasks to a smaller agent.
Use shell_command only for quick, single-step commands you can do directly.

Current working directory: {cwd}

Keep looping until the task is complete, then output the final response starting with <final>.
For responses where you are thinking or planning, do not use this tag. In these responses, don't include greetings, messages or questions to the user - this is your INTERNAL reasoning chain.
Every single response you send to the user must start with the token <final>.  """,
}

SUBAGENT_SYSTEM_PROMPT = {
    "role": "system",
    "content": """You are a subagent. You have been given a specific task to complete.
Use your tools to complete it step by step.
When the task is fully done, respond with <done> followed by a concise summary of what you accomplished and any relevant output.""",
}

session_id = uuid.uuid4()
base_path = pathlib.Path(f".nanoloop/{session_id}")
base_path.mkdir(parents=True, exist_ok=True)

main_messages = [system_prompt]
tokens = 0
todo_instance = todo.TodoManager(session_id)

# ── Chat history ──────────────────────────────────────────────────────────────


def message_to_dict(msg):
    """Convert a ChatCompletionMessage object to a JSON-serialisable dict."""
    d = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


def save_chat_history(messages):
    history_path = base_path / "messages.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=4)


def load_chat_history():
    history_path = base_path / "messages.json"
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print("⚠️ Error reading history file. Starting fresh.")
    return [system_prompt]


# ── Tool implementations ──────────────────────────────────────────────────────


def spawn_subagent(task, max_steps=10):
    """Run a full agentic loop with the small model to complete a delegated task."""
    messages = [
        SUBAGENT_SYSTEM_PROMPT,
        {"role": "user", "content": task},
    ]

    for step in range(max_steps):
        response = small_agent.chat(messages)
        response_message = response.choices[0].message
        content = response_message.content
        tool_calls = response_message.tool_calls

        if content and "<done>" in content:
            print(f"    ✓ Subagent finished in {step + 1} step(s)")
            return content.split("<done>", 1)[-1].strip()

        messages.append(message_to_dict(response_message))

        if tool_calls:
            for tool_call in tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                if fn_name == "shell_command":
                    print(f"    🖥️  [subagent] {truncate(fn_args['command'])}")
                    tool_result = shell_command(fn_args["command"])
                elif fn_name == "edit_file":
                    print(
                        f"    📝 [subagent] editing {truncate(fn_args['absolute_path'])}"
                    )
                    tool_result = edit_file(
                        fn_args["absolute_path"],
                        fn_args["original_string"],
                        fn_args["new_string"],
                    )
                else:
                    tool_result = f"Error: Tool '{fn_name}' not available to subagent."

                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": fn_name,
                        "content": tool_result,
                    }
                )
        elif content:
            messages.append(
                {
                    "role": "user",
                    "content": "Continue. When the task is complete, respond with <done> followed by a summary.",
                }
            )
        else:
            return "Subagent returned an empty response."

    return f"Subagent hit the {max_steps}-step limit without finishing. Last response: {content}"


def web_search(question):
    query = small_agent.say(
        f"Generate a short Google search query for the question: {question}"
    )
    search_results = DDGS().text(query, max_results=3)
    return small_agent.say(
        f"Summarize the search results using bullet points to answer '{question}': {search_results}"
    )


def shell_command(command):
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    output = result.stdout
    if result.returncode != 0:
        output += f"\n[ERROR exit code {result.returncode}]\n{result.stderr}"
    return output


def edit_file(absolute_path, original_string, new_string):
    try:
        with open(absolute_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"File {absolute_path} does not exist."

    count = content.count(original_string)
    if count == 0:
        return f"Warning: '{original_string}' not found in {absolute_path}. No changes made."
    if count > 1:
        return f"Expected exactly 1 occurrence of '{original_string}', but found {count}. Aborting."

    try:
        with open(absolute_path, "w", encoding="utf-8") as f:
            f.write(content.replace(original_string, new_string))
    except OSError as e:
        return f"Error writing to {absolute_path}: {e}"

    return "Edit successful"


def parse_tools(function_name, fn_args):
    try:
        if function_name == "web_search":
            print(f"🌐  Searching: {truncate(fn_args['question'])}")
            result = web_search(fn_args["question"])

        elif function_name == "shell_command":
            print(f"🖥️  Running: {truncate(fn_args['command'])}")
            result = shell_command(fn_args["command"])

        elif function_name == "spawn_subagent":
            print(f"🤖  Spawning subagent: {truncate(fn_args['task'])}")
            result = spawn_subagent(fn_args["task"])

        elif function_name == "edit_file":
            print(f"📝 Editing file: {truncate(fn_args['absolute_path'])}")
            result = edit_file(
                fn_args["absolute_path"],
                fn_args["original_string"],
                fn_args["new_string"],
            )

        elif function_name == "add_todo":
            print(f"📝 Adding todo: {truncate(fn_args['task'])}")
            result = json.dumps(todo_instance.add_todo(fn_args["task"]))
            todo_instance.print_todos()

        elif function_name == "mark_todo_complete":
            print(f"✅ Marking todo #{fn_args['task_number']} complete")
            result = json.dumps(
                todo_instance.mark_todo_complete(fn_args["task_number"])
            )
            todo_instance.print_todos()

        elif function_name == "edit_todo":
            print(f"✏️  Editing todo #{fn_args['task_number']}")
            result = json.dumps(
                todo_instance.edit_todo(fn_args["task_number"], fn_args["updated_task"])
            )
            todo_instance.print_todos()

        elif function_name == "clear_todo":
            print("🧹 Clearing all todos")
            result = json.dumps(todo_instance.clear_todo())
            todo_instance.print_todos()

        elif function_name == "view_todo":
            print("Viewing todos")
            result = json.dumps(todo_instance.view_todo())
            todo_instance.print_todos()

        else:
            print(f"⚠️  Unknown tool: {function_name}")
            result = f"Error: Tool '{function_name}' not valid."

    except Exception as e:
        result = f"ERROR: {e}"
        print(result)
    return result


def truncate(text, max_length=50, suffix="..."):
    if not text or len(text) <= max_length:
        return text
    half = (max_length - len(suffix)) // 2
    return text[:half] + suffix + text[-half:]


def parse_slash_command(command):
    global main_messages, tokens, session_id, base_path, todo_instance
    if "/clear" in command:
        print("--------- CLEARED ---------")
        console.clear()
        main_messages = [system_prompt]
        tokens = 0
    elif "/resume" in command:
        parts = command.split(" ")
        if len(parts) < 2 or not parts[1].strip():
            print("⚠️  Usage: /resume <session_id>")
            return
        session_id = parts[1].strip()
        base_path = pathlib.Path(f".nanoloop/{session_id}")
        main_messages = load_chat_history()
        todo_instance = todo.TodoManager(session_id)
        print(f"✅ Resumed session: {session_id}")
    elif "/exit" in command:
        print("bye bye!")
        print(f"To resume, type /resume {session_id}")
        sys.exit()


# ── Main loop ─────────────────────────────────────────────────────────────────

print(r"""
                          _
                         | |
  _ __   __ _ _ __   ___ | | ___   ___  _ __
 | '_ \ / _` | '_ \ / _ \| |/ _ \ / _ \| '_ \
 | | | | (_| | | | | (_) | | (_) | (_) | |_) |
 |_| |_|\__,_|_| |_|\___/|_|\___/ \___/| .__/
                                       | |
                                       |_|
                                       """)
print(f"• big model: {big_agent.model} • small model: {small_agent.model}")

while True:
    try:
        user_message = input(f"\nnanoloop ({tokens} tokens used)>")

        if not user_message.strip():
            continue

        if user_message.startswith("/"):
            parse_slash_command(user_message)
            continue

        # ── Agent loop ────────────────────────────────────────────────────────────
        main_messages.append({"role": "user", "content": user_message})
        save_chat_history(main_messages)

        while True:
            response = big_agent.chat(main_messages)

            if response.usage:
                tokens += (
                    response.usage.prompt_tokens + response.usage.completion_tokens
                )

            response_message = response.choices[0].message
            content = response_message.content
            tool_calls = response_message.tool_calls

            if content and content.strip().startswith("<final>"):
                print("\n")
                with Live(Markdown(""), console=console, refresh_per_second=15) as live:
                    display_text = content.replace("<final>", "", 1).strip()
                    for i in range(0, len(display_text), 8):
                        live.update(Markdown(display_text[: i + 8]))
                        sleep(0.005)
                main_messages.append({"role": "assistant", "content": content})
                save_chat_history(main_messages)
                break

            main_messages.append(message_to_dict(response_message))
            save_chat_history(main_messages)

            if tool_calls:
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)
                    result = parse_tools(function_name, fn_args)
                    main_messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": result,
                        }
                    )
                    save_chat_history(main_messages)
            elif content:
                print(f"💭 {truncate(content.strip())}")
                main_messages.append(
                    {
                        "role": "user",
                        "content": "Continue working. If you have a final answer for the user, start your response with <final>.",
                    }
                )
                save_chat_history(main_messages)
            else:
                print("⚠️  Empty response.")
                break

    except Exception as e:
        print(f"ERROR: {e}")
        print(f"To resume, type /resume {session_id}")
