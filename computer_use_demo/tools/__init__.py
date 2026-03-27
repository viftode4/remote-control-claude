import platform

from .base import CLIResult, ToolResult
from .collection import ToolCollection
from .edit import EditTool

if platform.system() == "Windows":
    from .computer_windows import ComputerTool
    from .bash_windows import BashTool
else:
    from .computer import ComputerTool
    from .bash import BashTool

__ALL__ = [
    BashTool,
    CLIResult,
    ComputerTool,
    EditTool,
    ToolCollection,
    ToolResult,
]
