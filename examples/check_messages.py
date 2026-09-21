from tau_agent.messages import AssistantMessage, TextContent, UserMessage

user = UserMessage(content="你好")
assistant = AssistantMessage(content=[TextContent(text="你好！")])

assert user.role == "user"
assert user.content == "你好"
assert assistant.role == "assistant"
assert assistant.content[0].type == "text"
assert assistant.content[0].text == "你好！"

print("消息类型检查通过")