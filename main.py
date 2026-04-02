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

console = Console()


SMALL_MODEL = "unsloth/Qwen3.5-0.8B-GGUF:UD-Q4_K_XL"
BIG_MODEL = "unsloth/Qwen3.5-0.8B-GGUF:UD-Q4_K_XL"

BIG_MODEL_TOTAL_CONTEXT = 4096

big_model_process = None
small_model_process = None

def start_servers():
    global big_model_process, small_model_process
    big_model_process = subprocess.Popen([
        "/home/pi/llama.cpp/build/bin/llama-server", 
        "-hf", BIG_MODEL, 
        "--host", "0.0.0.0", "--port", "8080", "-c", str(BIG_MODEL_TOTAL_CONTEXT), "--reasoning-budget", "0", "--parallel", "1", "--webui-mcp-proxy", "--threads", "2", "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-prompt", "--ubatch-size", "512", "-ctv", "q8_0", "--threads-batch", "4", "--no-mmproj"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    small_model_process = subprocess.Popen([
        "llama-server", 
        "-hf", SMALL_MODEL, 
        "--host", "0.0.0.0", "--port", "8081", "-c", "6000", "--reasoning-budget", "0", "--parallel", "1", "--webui-mcp-proxy", "--threads", "2", "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-prompt", "--ubatch-size", "512", "-ctv", "q8_0", "--threads-batch", "4", "--no-mmproj"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

big_model_client = OpenAI(
    base_url="http://localhost:8080/v1", 
    api_key="s" 
)

small_model_client = OpenAI(
    base_url="http://localhost:8081/v1", 
    api_key="sk-no-key-required" # A dummy key is required by llama.cpp
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
            "description": "Execute bash commands on the local system. Use this to read and edit files, run python code, check system status, and other terminal tasks. Output is returned as a string.",
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
    }
]

main_messages = [] # list of messages in the main agent
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
            tokens += response.usage.prompt_tokens
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        # If there are no tool calls, the model is ready to give the final answer
        if not tool_calls:
            break 

        # If there ARE tool calls, process them and STAY in the loop
        main_messages.append(response_message) 
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            
            if function_name == "web_search":
                print(f"🌐  Searching: {args['question']}")
                result = web_search(args['question'])
                
            elif function_name == "shell_command":
                print(f"🖥️  Running: {args['command']}")
                result = shell_command(args['command'])
            
            main_messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": result,
            })
            
    stream = big_model_client.chat.completions.create(
        model=BIG_MODEL,
        messages=main_messages,
        stream=True,
        stream_options={"include_usage": True}
    )
    
    full_message = ""
    usage_stats = None
    
    print("\n")
    
    with Live(Markdown(""), console=console, refresh_per_second=10) as live:
        for chunk in stream:
            if hasattr(chunk, 'usage') and chunk.usage is not None:
                usage_stats = chunk.usage
                
            if not chunk.choices:
                continue
            
            content = chunk.choices[0].delta.content
            
            if content:
                full_message += content
                # Update the live display with the new full string parsed as Markdown
                live.update(Markdown(full_message))
            
    if usage_stats:
        tokens += usage_stats.total_tokens
    
    return(str(full_message))


# TOOL FUNCTIONS

def web_search(question):
    # Generate the search query
    search_query = small_model_client.chat.completions.create(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": f"Generate a short Google search query for the question {question}"}]
    )
    
    search_results = DDGS().text(search_query.choices[0].message.content, max_results=3, backend='duckduckgo')
    
    # Summarize the search results
    summary = small_model_client.chat.completions.create(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": f"Summarize the search results using bullet points to answer the question {question}: {search_results}"}]
    )
    
    return summary.choices[0].message.content

def shell_command(command):
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    return result.stdout

# parses slash commands, right now only /clear
def parse_slash_command(command):
    if "/clear" in command:
        print("--------- CLEARED ---------")
        main_messages = []
        tokens = 0

print("Starting llama.cpp server")
start_servers()
sleep(10)

print("""
                          _                   
                         | |                  
  _ __   __ _ _ __   ___ | | ___   ___  _ __  
 | '_ \ / _` | '_ \ / _ \| |/ _ \ / _ \| '_ \ 
 | | | | (_| | | | | (_) | | (_) | (_) | |_) |
 |_| |_|\__,_|_| |_|\___/|_|\___/ \___/| .__/ 
                                       | |    
                                       |_|
                                       """)

try:
    while True:
        token_percentage = round((tokens / BIG_MODEL_TOTAL_CONTEXT) * 100)
        user_message = input(f"\nnanoloop ({tokens} tokens / {token_percentage}% used)>")
        
        if user_message[0] == "/":
            parse_slash_command(user_message)
        else:
            ask_big_model(user_message)
        
except KeyboardInterrupt:
    big_model_process.terminate()
    small_model_process.terminate()

