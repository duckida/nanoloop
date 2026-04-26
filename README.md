# nanoloop
Small Python-based agent loop for nano local models!
Designed to run with local models but works with anything.

<img width="661" height="392" alt="Screenshot 2026-04-01 at 4 32 38 PM" src="https://github.com/user-attachments/assets/5259954f-f93c-4256-9665-7e16bd200567" />

[video demo](https://docs.google.com/videos/d/1fNEpXDZw1tccgVNDhWfvO3ijx5BdTW03cPFWF_T1IEQ/edit?usp=sharing)


## Features
- Connects to OpenAI compatible servers (llama.cpp, Ollama, LM Studio, Qwen, Gemini etc.)
- Big and small model settings (small model used to summarize web searches and for multi step bash commands)
- Web search, todo, file edit and shell command tools
- Markdown rendering

[Here](https://gisthost.github.io/?2f876b475934a99a34912fa9701eb435) is an example of an app implemented by nanoloop!

How to run: 

### Steps
1. Install `uv`
2. Download the repo: `git clone https://github.com/duckida/nanoloop && cd nanoloop`
3. Install packages `uv sync`
4. Run with correct arguments
**Local models:** `uv run main.py -bb {big model base url} -sb {small model base url} -small {small model name} -big {big model name}`
**Cloud models:**
bash```
uv run main.py \
  -bb {big model base url} \
  -sb {small model base url} \
  -big {big model name} \
  -small {small model name} \
  -ba {big model API key} \
  -sa {small model API key}```

Like this you can mix and match LLMs from different providers, cloud and local. For example, the big model is a cloud model and the small model is local.

> Note: there is no warranty with nanoloop. It uses LLMs and may delete files on your device. Use at your own risk.
