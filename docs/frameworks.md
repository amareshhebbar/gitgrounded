# Benchmark any framework, agent or API

`gitgrounded benchmark` runs every target on the same locked, AI generated question set and produces a leaderboard and, with `--certify`, a signed certificate.

```bash
gitgrounded benchmark --spec spec.txt --context policy.md --certify --open
gitgrounded benchmark --target langgraph_agent --target strands_agent --spec spec.txt
```

`--spec` is the system prompt or a plain description of what the agents must do. Questions and expected answers are generated from it, so every target faces the same test.

## Python frameworks

Point `entry` at an object or a factory. `module:object` loads an object, `module:factory()` calls a function to build it. `framework: auto` detects the framework from the object's module.

```yaml
targets:
  lg:
    type: framework
    entry: my_app.graph:build_graph()
    framework: auto
  strands:
    type: framework
    entry: my_app.agent:agent
  crew:
    type: framework
    entry: my_app.crew:build_crew()
    options: {input_key: question}
  haystack:
    type: framework
    entry: my_app.rag:pipeline
    framework: haystack
    options:
      input: {prompt_builder: {query: "{{input}}"}}
      output: llm.replies
```

| framework | how it is called | tool calls recorded |
|---|---|---|
| langgraph | `invoke({"messages": [...]}, thread_id)` | yes, from AI and tool messages |
| langchain | `invoke(messages)` or `invoke(options.input)` | yes, when messages are returned |
| strands | `agent(prompt)` per user turn | yes, toolUse and toolResult blocks |
| crewai | `kickoff(inputs={input_key: text})` | no |
| openai_agents | `Runner.run_sync(agent, input)` | yes, ToolCallItem |
| pydantic_ai | `run_sync(prompt)` | yes, tool call parts |
| llamaindex | `chat`, `query` or async `run(user_msg)` | retrieved nodes become context |
| autogen | async `run(task)` | yes, function call content |
| smolagents | `run(task)` | no |
| haystack | `run(options.input)` with `options.output` path | no |
| dspy | `module(**{input_field: text})` | no |
| generic | first of `invoke`, `run`, `chat`, `kickoff`, `query`, or a direct call; async supported | when the result has `tool_calls` |

Any framework not listed works through `generic` or a three line `run(case_input, ctx)` function with `type: python`.

Options: `messages_key`, `extra_input`, `input` template with `{{input}}`, `output` dotted path, `input_key`, `input_field`, `output_field`, `methods`.

## Remote agents and servers

| type | protocol |
|---|---|
| `a2a` | A2A JSON RPC `message/send`, keeps `contextId` across turns |
| `adk` | Google ADK `adk api_server`: session plus `/run`, records function calls |
| `mcp` | MCP stdio or HTTP; an agent model selects a tool; `case.context.fixtures` sandboxes tool results |
| `http` | any JSON API with a body template and JSONPath output |
| `openai_chat` | a system prompt on any configured provider |

Set `GITGROUNDED_HTTP_ALLOW=api.example.com,localhost` to restrict which hosts network targets may call.
