import type { AgentEvent } from "../api";
import type { AgentStep, Step } from "../components/Messages";

/** Apply a change to the delegation (agent step) with this id. */
function updateAgent(steps: Step[], id: string, fn: (s: AgentStep) => AgentStep): Step[] {
  return steps.map((s) => (s.type === "agent" && s.id === id ? fn(s) : s));
}

/** Apply one streamed event to the steps of the current turn. */
export function applyEvent(steps: Step[], event: AgentEvent): Step[] {
  const last = steps[steps.length - 1];
  switch (event.type) {
    case "token":
      return last?.type === "text"
        ? [...steps.slice(0, -1), { type: "text", text: last.text + event.text }]
        : [...steps, { type: "text", text: event.text }];
    case "agent_start":
      return [
        ...steps,
        { type: "agent", id: event.id, agent: event.agent, title: event.title, task: event.task, tools: [], startedAt: performance.now() },
      ];
    case "agent_end":
      return updateAgent(steps, event.id, (s) => ({ ...s, isError: event.is_error, finishedAt: performance.now() }));
    case "tool_call":
      return updateAgent(steps, event.delegation, (s) => ({
        ...s,
        tools: [...s.tools, { type: "tool", id: event.id, name: event.name, input: event.input, startedAt: performance.now() }],
      }));
    case "tool_result":
      return updateAgent(steps, event.delegation, (s) => ({
        ...s,
        tools: s.tools.map((t) =>
          t.id === event.id ? { ...t, output: event.output, isError: event.is_error, finishedAt: performance.now() } : t,
        ),
      }));
    case "error":
      return [...steps, { type: "error", message: event.message }];
    default:
      return steps;
  }
}
