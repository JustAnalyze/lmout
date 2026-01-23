
from rich.console import Console
from rich.align import Align
from rich.panel import Panel
from rich.text import Text
import pyfiglet
import time

def display():
    """
    Displays a centered, full-screen message using Rich and Pyfiglet.
    """
    console = Console()

    # 1. Generate the Figlet art
    font = pyfiglet.Figlet(font='block')
    art_text = font.renderText('TOUCH GRASS')

    # 2. Create the subtext
    subtext = Text(
        "\n...AND GO TOUCH SOME ACTUAL GRASS.\n\nRelocking this machine in 3 seconds.",
        justify="center",
        style="bold yellow"
    )

    # 3. Combine them into a single renderable group
    full_text = Text.from_markup(f"[bold green]{art_text}[/bold green]") + subtext

    # 4. Center the entire content vertically and horizontally
    centered_content = Align.center(full_text, vertical="middle")
    
    # 5. Clear the screen and print the content
    console.clear()
    console.print(centered_content)
    
    # 6. Wait before exiting, allowing the message to be read
    time.sleep(3)

if __name__ == "__main__":
    display()

