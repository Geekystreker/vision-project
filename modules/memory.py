class Memory:
    def __init__(self):
        self.last_command = None
        self.last_intent = None
        self.last_suggestion = None

    def update_command(self, cmd):
        self.last_command = cmd

    def set_suggestion(self, suggestion):
        self.last_suggestion = suggestion

    def clear_suggestion(self):
        self.last_suggestion = None
