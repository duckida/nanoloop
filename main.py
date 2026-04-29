from openai import OpenAI
import subprocess
import requests
from time import sleep
from ddgs import DDGS
import sys
import json

from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
import argparse

console = Console()

big_model_process = None
small_model_process = None

parser = argparse.ArgumentParser(description="nanoloop: agent CLI for small models")

# uv run main.py -bb http://localhost:4321/v1 -sb http://localhost:1234/v1 -big big-model-name -small small-model-name
parser.add_argument("-bb", "--big-model-base-url", type=str, help="OpenAI-compatible base url for big model (eg https://localhost:8080/v1)")
parser.add_argument("-sb", "--small-model-base-url", type=str, help="OpenAI-compatible base url for small model (eg https://localhost:5050/v1)")

parser.add_argument("-small", "--small-model-name", type=str, help="Model ID for small model")
parser.add_argument("-big", "--big-model-name", type=str, help="Model ID for big model")

parser.add_argument("-sa", "--small-api-key", type=str, help="API key for small model")
parser.add_argument("-ba", "--big-api-key", type=str, help="API key for big model")

args = parser.parse_args()

SMALL_MODEL = args.small_model_name
BIG_MODEL = args.big_model_name

BIG_BASE_URL = args.big_model_base_url
SMALL_BASE_URL = args.small_model_base_url

SMALL_API_KEY = args.small_api_key
BIG_API_KEY = args.big_api_key

big_model_client = OpenAI(
    base_url=BIG_BASE_URL, 
    api_key=BIG_API_KEY if BIG_API_KEY else "sk-no-key-required"
)

small_model_client = OpenAI(
    base_url=SMALL_BASE_URL, 
    api_key=SMALL_API_KEY if SMALL_API_KEY else "sk-no-key-required"
)

tools = [
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
                        "description": "The specific question to answer with web results.",
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
            "description": "Execute bash commands on the local system. Use this to read and edit files, run python code, check system status, and other terminal tasks. Output is returned as a string. ONLY run commands within the current directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The full bash command to execute (e.g., 'cat file.txt', 'ls -la', or 'python3 script.py').",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_computer",
            "description": "Provide a task to a smaller LLM which will convert it to a Bash command, run it and return the output in the form you request. Output is returned as a string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task the smaller agent must use Bash for and the desired return format.",
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
            "description": "Add a new task to the todo list. Returns the updated list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task description to add."
                    }
                },
                "required": ["task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_todo_complete",
            "description": "Mark a todo item as complete by its 1-based number (e.g., 1 for first item).",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_number": {
                        "type": "integer",
                        "description": "The 1-based position of the todo to mark complete (e.g., 1, 2, 3)."
                    }
                },
                "required": ["task_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_todo",
            "description": "Edit an existing todo's text by its 1-based number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_number": {
                        "type": "integer",
                        "description": "The 1-based position of the todo to edit."
                    },
                    "updated_task": {
                        "type": "string",
                        "description": "The new task description."
                    }
                },
                "required": ["task_number", "updated_task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_todo",
            "description": "Clear all items from the todo list.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_todo",
            "description": "View the todo list."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file surgically by replacing a unique string with a new string. Fails safely if the original string is not found or appears more than once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "absolute_path": {
                        "type": "string",
                        "description": "The absolute path to the file to edit."
                    },
                    "original_string": {
                        "type": "string",
                        "description": "The unique string in the file to replace."
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The string to replace it with."
                    }
                },
                "required": ["absolute_path", "original_string", "new_string"]
            }
        }
    },
    
] 

system_prompt = {"role": "system", "content": """
You are nanoloop, a lightweight AI agent running on a local LLM.
Act efficiently and correctly to complete the user's tasks.

ALWAYS use the todo list for ANY multi-step tasks and specify what tools you will use in it.
Use the `use_computer` tool for most shell tasks including indexing, but not for single-command tasks or file editing.

Keep looping until the task is complete, then output the final response starting with <final>.
For responses where you are thinking or planning, do not use this tag. In these responses, don't include greetings, messages or questions to the user - this is your INTERNAL reasoning chain.
Every single response you send to the user must start with the token <final>.  """
}

main_messages = [system_prompt] # list of messages in the main agent
tokens = 0 # tokens used so far

def ask_big_model(user_message):
    global tokens
    
    # Add the user message to the chat history
    main_messages.append({"role": "user", "content": user_message})
    
    while True: # Keep looping until the model provides a text response instead of a tool call
        response = big_model_client.chat.completions.create(
            model=BIG_MODEL,
            messages=main_messages,
            tools=tools,
            tool_choice="auto"
        )
        
        if response.usage:
            tokens += response.usage.prompt_tokens + response.usage.completion_tokens
        
        response_message = response.choices[0].message
        content = response_message.content
        tool_calls = response_message.tool_calls

        # If there are no tool calls, the model is ready to give the final answer
        if content and content.strip().startswith("<final>") :
            final_content = content
    
            print("\n")
            with Live(Markdown(""), console=console, refresh_per_second=15) as live:
                # Simulate streaming for visual polish (optional)
                display_text = final_content.replace("<final>", "", 1).strip()
                for i in range(0, len(display_text), 8):
                    chunk = display_text[i:i+8]
                    live.update(Markdown(chunk if i == 0 else display_text[:i+8]))
                    sleep(0.005)  # Tiny delay for smooth effect
            
            # Append the final response to history for consistency
            main_messages.append({"role": "assistant", "content": final_content})
            
            return final_content

        # If there ARE tool calls, process them and STAY in the loop
        main_messages.append(response_message) 
        
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                result = parse_tools(function_name, args)
                
                main_messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": result,
                })
            
        else:  
            if content:
                print(f"💭 {truncate(content.strip())}")
                main_messages.append({
                    "role": "user",
                    "content": "Continue working. If you have a final answer for the user, start your response with <final>."
                })
            else:
                print("⚠️  Empty response - breaking loop.")
                break


# TOOL FUNCTIONS
def parse_tools(function_name, args):
    try:
        if function_name == "web_search":
            print(f"🌐  Searching: {truncate(args['question'])}")
            result = web_search(args['question'])
            
        elif function_name == "shell_command":
            print(f"🖥️  Running: {truncate(args['command'])}")
            result = shell_command(args['command'])
            
        elif function_name == "use_computer":
            print(f"🖥️  Using computer: {truncate(args['task'])}")
            result = use_computer(args['task'])
        
        elif function_name == "edit_file":
            print(f"📝 Editing file: {truncate(args['absolute_path'])}")
            result = edit_file(args['absolute_path'], args['original_string'], args['new_string'])
        
        elif function_name == "add_todo":
            print(f"📝 Adding todo: {truncate(args['task'])}")
            result = add_todo(args['task'])
            _print_todos_pretty(result)  # ✅ Pretty console output
            result = json.dumps(result)
            
        elif function_name == "mark_todo_complete":
            print(f"✅ Marking todo #{args['task_number']} complete")
            result = mark_todo_complete(args['task_number'])
            _print_todos_pretty(result)
            result = json.dumps(result)
            
        elif function_name == "edit_todo":
            print(f"✏️  Editing todo #{args['task_number']}")
            result = edit_todo(args['task_number'], args['updated_task'])
            _print_todos_pretty(result)
            result = json.dumps(result)
            
        elif function_name == "clear_todo":
            print("🧹 Clearing all todos")
            result = clear_todo()
            _print_todos_pretty(result)
            result = json.dumps(result)
        
        elif function_name == "view_todo":
            print("Viewing todos")
            result = view_todo()
            _print_todos_pretty(result)
            result = json.dumps(result)
            
        else:
            print(f"⚠️  Unknown tool: {function_name}")
            result = f"Error: Tool '{function_name}' not valid."
            
    except Exception as e:
        result = f"ERROR: {e}"
        print(result)
    return result
    


def web_search(question):
    # Generate the search query
    search_query = small_model_client.chat.completions.create(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": f"Generate a short Google search query for the question {question}"}]
    )
    
    search_results = DDGS().text(search_query.choices[0].message.content, max_results=3)
    
    # Summarize the search results
    summary = small_model_client.chat.completions.create(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": f"Summarize the search results using bullet points to answer the question {question}: {search_results}"}]
    )
    
    return summary.choices[0].message.content

def shell_command(command):
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    return result.stdout
         

def use_computer(task):
    # 1. Generate command
    response = small_model_client.chat.completions.create(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": f"Output ONLY a bash command to: {task}"}],
        timeout=30  # ← critical: prevent hanging
    )
    cmd = response.choices[0].message.content.strip().strip("`")
    
    # 2. Run command + capture BOTH stdout and stderr
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=60)
    
    # 3. Build result string that includes errors if they happened
    output = result.stdout
    if result.returncode != 0:
        output += f"\n[ERROR exit code {result.returncode}]\n{result.stderr}"
    
    # 4. Let small model format the answer (optional but helpful)
    final = small_model_client.chat.completions.create(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": f"Task: {task}\nOutput:\n{output}\n\nSummarize the result:"}],
        timeout=120
    )
    return final.choices[0].message.content

def edit_file(absolute_path, original_string, new_string):
    try:
        with open(absolute_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"File {absolute_path} does not exist.")
        result = f"File {absolute_path} does not exist."
        return result
        
    
    occurrence_count = content.count(original_string)
    if occurrence_count == 0:
        result = f"Warning: '{original_string}' not found in {absolute_path}. No changes made."
        return result
    if occurrence_count > 1:
        result = f"Expected exactly 1 occurrence of '{original_string}', but found {occurrence_count} in {absolute_path}. Aborting to prevent unintended changes."
        return result
    
    new_content = content.replace(original_string, new_string)

    # Write back to file
    try:
        with open(absolute_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    except OSError as e:
        return f"Error writing to {absolute_path}: {e}"

    return "Edit successful"


# todo list tools
agent_todo = []

def view_todo():
    return agent_todo

def add_todo(task):
    formatted_task = f"{(len(agent_todo)+1)}: {task}"
    agent_todo.append(formatted_task)
    return agent_todo
    
def mark_todo_complete(task_number):
    index = task_number - 1
    agent_todo[index] = f"DONE: {agent_todo[index]}"
    return agent_todo

def edit_todo(task_number, updated_task):
    index = task_number - 1
    agent_todo[index] = updated_task
    return agent_todo

def clear_todo():
    global agent_todo
    agent_todo = []
    return agent_todo

def _print_todos_pretty(todos_list: list):
    """Print the todo list nicely to console using Rich formatting. Accepts a Python list."""
    console.print("\n📋 [bold cyan]Current Todo List:[/bold cyan]")
    
    if not todos_list:
        console.print("   [dim]• (no items)[/dim]")
    else:
        for item in todos_list:
            if item.startswith("DONE:"):
                # Strikethrough completed items
                task_text = item.replace("DONE: ", "")
                console.print(f"   [dim strike]• {task_text}[/dim strike]")
            elif ":" in item:
                # Regular numbered item
                console.print(f"   • [green]{item}[/green]")
            else:
                console.print(f"   • {item}")
    console.print("")  # Extra spacing

def truncate(text, max_length=50, suffix="..."):
    """Truncate text to max_length, adding suffix if truncated."""
    if not text or len(text) <= max_length:
        return text
    # Show start + end with ellipsis in middle
    half = (max_length - len(suffix)) // 2
    return text[:half] + suffix + text[-half:]

# parses slash commands, right now only /clear
def parse_slash_command(command):
    global main_messages, tokens
    if "/clear" in command:
        print("--------- CLEARED ---------")
        console.clear()
        main_messages = [system_prompt]
        tokens = 0
    elif "/exit" in command:
        print("bye bye!")
        sys.exit()

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
print(f"• big model: {BIG_MODEL} • small model: {SMALL_MODEL}")

while True:
    user_message = input(f"\nnanoloop ({tokens} tokens used)>")
    
    if user_message[0] == "/":
        parse_slash_command(user_message)
    else:
        ask_big_model(user_message)
        


