from openai import OpenAI


class Agent:
    def __init__(self, base_url, api_key, model, tools=None):
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key if api_key else "sk-no-key-required",
        )
        self.model = model
        self.tools = tools or []

    def chat(self, messages, tool_choice="auto"):
        """Single completion call. Returns the full response object."""
        kwargs = dict(model=self.model, messages=messages)
        if self.tools:
            kwargs["tools"] = self.tools
            kwargs["tool_choice"] = tool_choice
        return self.client.chat.completions.create(**kwargs)

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
