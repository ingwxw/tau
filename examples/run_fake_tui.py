from pathlib import Path

from tau_ai.fake import FakeProvider
from tau_coding.session import create_coding_session
from tau_coding.tui.app import TauTuiApp


session = create_coding_session(
    project_dir=Path.cwd(),
    provider=FakeProvider(),
    model="fake",
    system="你是一个编码助手。",
)

TauTuiApp(
    session,
    provider_name="fake",
    model="fake",
).run()
