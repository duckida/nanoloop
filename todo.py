# todo list tools

import json
import pathlib

from rich.console import Console

console = Console()


class TodoManager:
    session_id = ""

    def __init__(self, session_id):
        self.session_id = session_id

        self.base_path = pathlib.Path(f".nanoloop/{session_id}")
        self.file_path = self.base_path / "todo.txt"

        # Create the directory if it doesn't exist
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Initialize the file if it doesn't exist
        if not self.file_path.exists():
            self.file_path.write_text("[]")

    def _load_list(self) -> list:
        """Helper: Reads the file and converts JSON string back to a Python list."""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_list(self, todo_list):
        """Helper: Converts the Python list to JSON and saves it to the file."""
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(todo_list, f, indent=4)

    def view_todo(self):
        return self._load_list()

    def add_todo(self, task):
        todo_list = self._load_list()
        # Create the numbered format you liked
        formatted_task = f"{len(todo_list) + 1}: {task}"
        todo_list.append(formatted_task)

        self._save_list(todo_list)
        return todo_list

    def mark_todo_complete(self, task_number):
        todo_list = self._load_list()
        index = task_number - 1

        if 0 <= index < len(todo_list):
            if not todo_list[index].startswith("DONE:"):
                todo_list[index] = f"DONE: {todo_list[index]}"
            self._save_list(todo_list)

        return todo_list

    def clear_todo(self):
        self._save_list([])
        return []

    def edit_todo(self, task_number, updated_task):
        """Replaces the text of an existing task while keeping its number."""
        todo_list = self._load_list()
        index = task_number - 1

        # Validation: Check if the task number actually exists
        if 0 <= index < len(todo_list):
            original_item = todo_list[index]

            # Check if the original was completed
            is_done = original_item.startswith("DONE:")

            # Reformat the new task with the same number
            # We use task_number directly to keep the 1-based indexing
            new_formatted = f"{task_number}: {updated_task}"

            # If it was done, you might want to preserve that status
            if is_done:
                new_formatted = f"DONE: {new_formatted}"

            todo_list[index] = new_formatted
            self._save_list(todo_list)
            console.print(f"[yellow]Edited task {task_number}:[/yellow] {updated_task}")
        else:
            console.print(f"[bold red]Error:[/bold red] Task #{task_number} not found.")

        return todo_list

    def print_todos(self):
        """Print the todo list nicely to console using Rich formatting."""
        todos_list = self.view_todo()

        console.print(
            f"\n📋 [bold cyan]Todo List Session:[/bold cyan] [yellow]{self.session_id}[/yellow]"
        )
        console.print("─" * 30)

        if not todos_list:
            console.print("   [dim]• (no items)[/dim]")
        else:
            for item in todos_list:
                # 1. Handle Completed Items
                if item.startswith("DONE:"):
                    # Strip 'DONE:' and the original number for a cleaner look
                    clean_text = item.replace("DONE: ", "")
                    console.print(f"   [dim strike]✔ {clean_text}[/dim strike]")

                # 2. Handle Pending Items
                else:
                    # Make the task ID (the number) bold green
                    if ":" in item:
                        parts = item.split(":", 1)
                        task_id = parts[0]
                        task_text = parts[1]
                        console.print(
                            f"   [bold green]{task_id:>2}:[/bold green][white]{task_text}[/white]"
                        )
                    else:
                        console.print(f"   • {item}")

        console.print("─" * 30 + "\n")
