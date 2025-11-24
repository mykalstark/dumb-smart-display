class Display:
    def __init__(self, simulate: bool = True):
        self.simulate = simulate
        if simulate:
            print("[Display] SIMULATION mode.")
        else:
            print("[Display] HARDWARE mode initialized.")

    def render_text(self, text: str):
        if self.simulate:
            print('========== DISPLAY ==========')
            print(text)
            print('==============================')
        else:
            pass  # TODO: real driver here
