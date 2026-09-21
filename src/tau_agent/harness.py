from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from inspect import isawaitable

from tau_agent.cancellation import CancellationToken
from tau_agent.events import AgentEvent
from tau_agent.loop import run_agent_loop
from tau_agent.messages import AgentMessage, UserMessage
from tau_agent.provider import ModelProvider
from tau_agent.session import MessageEntry, SessionState, SessionStorage
from tau_agent.tools import AgentTool

# 定义监听器类型
type EventListener = Callable[[AgentEvent], Awaitable[None] | None]

class AgentHarness:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        model: str,
        system: str,
        tools: list[AgentTool],
        max_turns: int = 10,
        session_storage: SessionStorage | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._system = system
        self._tools = list(tools)
        self._max_turns = max_turns
        self._session_storage = session_storage
        if session_storage is None:
            self._messages = []
            self._active_entry_id: str | None = None
        else:
            state = SessionState.from_entries(session_storage.read_all())
            self._messages = list(state.messages)
            self._active_entry_id = state.active_leaf_id
        self._persisted_message_count = len(self._messages)
        self._running = False
        self._listeners: list[EventListener] = []
        self._current_token: CancellationToken | None = None

    async def prompt(self, content: str) -> AsyncGenerator[AgentEvent, None]:
        if self._running:
            raise RuntimeError("AgentHarness 正在运行")
        self._running = True
        token = CancellationToken()
        self._current_token = token
        try:
            loop_stream =  run_agent_loop(
                    provider=self._provider,
                    model=self._model,
                    system=self._system,
                    tools=self._tools,
                    messages=self._messages,
                    prompt=UserMessage(content),
                    max_turns=self._max_turns,
                    signal=token
            )
            async with aclosing(loop_stream):
                async for event in loop_stream:
                    self._persist_new_messages()
                    for listener in tuple(self._listeners):
                        result = listener(event)
                        if isawaitable(result):
                            await result
                    yield event

        finally:
            self._persist_new_messages()
            self._current_token = None
            self._running = False

    def _persist_new_messages(self) -> None:
        if self._session_storage is None:
            return

        while self._persisted_message_count < len(self._messages):
            entry = MessageEntry(
                message=self._messages[self._persisted_message_count],
                parent_id=self._active_entry_id,
            )
            self._session_storage.append(entry)
            self._active_entry_id = entry.id
            self._persisted_message_count += 1
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return tuple(self._messages)

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        self._listeners.append(listener)
        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return unsubscribe
    def cancel(self) -> None:
        if self._current_token is not None:
            self._current_token.cancel()
