from openai import OpenAI
import openai

class Agent:
    def __init__(self, base_url, api_key, model, tools=None):
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key if api_key else "sk-no-key-required",
        )
        self.model = model
        self.tools = tools or []

    def chat(self, messages, tool_choice="auto", max_retries=5, base_delay=2):
        """Single completion call with retry on transient errors."""
        kwargs = dict(model=self.model, messages=messages)
        if self.tools:
            kwargs["tools"] = self.tools
            kwargs["tool_choice"] = tool_choice

        for attempt in range(max_retries):
            try:
                return self.client.chat.completions.create(**kwargs)
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                if attempt == max_retries - 1:
                    raise
                delay = base_delay * (2**attempt)
                print(
                    f"⚠️  Connection error, retrying in {delay}s... ({attempt + 1}/{max_retries})"
                )
                time.sleep(delay)
            except openai.APIStatusError as e:
                if e.status_code < 500:
                    raise  # don't retry 4xx (auth, bad request, etc.)
                if attempt == max_retries - 1:
                    raise
                delay = base_delay * (2**attempt)
                print(
                    f"⚠️  Server error {e.status_code}, retrying in {delay}s... ({attempt + 1}/{max_retries})"
                )
                time.sleep(delay)

    def say(self, prompt, system=None, timeout=None):
        """Convenience method for a single-turn prompt → string reply."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs = dict(model=self.model, messages=messages)
        if timeout:
            kwargs["timeout"] = timeout
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
