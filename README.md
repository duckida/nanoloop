# nanoloop
Small Python-based agent loop for nano local models!
Designed to run with local models on a Pi 5!

<img width="661" height="392" alt="Screenshot 2026-04-01 at 4 32 38 PM" src="https://github.com/user-attachments/assets/5259954f-f93c-4256-9665-7e16bd200567" />


## Features
- Connects to llama.cpp
- Big and small model settings (small model used to summarize web searches)
- Web search and shell command tools
- Markdown rendering & streaming

How to run: 
0. Ensure llama.cpp is installed with model `unsloth/Qwen3.5-0.8B-GGUF:UD-Q4_K_XL` (this can be changed in the code)
1. Install `uv`
2. Download the repo: `git clone https://github.com/duckida/nanoloop && cd nanoloop`
3. Install packages `uv sync`
4. Run with `uv run main.py`

> Note: there is no warranty with nanoloop. It uses small LLMs and may delete files on your device. Use at your own risk.
