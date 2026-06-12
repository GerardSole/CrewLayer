/**
 * Next.js route handler — streaming chatbot with persistent CrewLayer memory.
 *
 * What this does:
 *  1. Recalls relevant long-term memories before the LLM call
 *     → the model already "knows" the user from previous sessions
 *  2. Streams the response back using CrewLayerDataStream
 *     → every completed response is automatically logged as an action
 *  3. Persists the new messages after each turn
 *     → memory grows with every conversation
 *
 * The client sends:  { messages: CoreMessage[], sessionId?: string }
 * The server streams: plain text chunks (text/plain)
 */

import { streamText } from "ai";
import { anthropic } from "@ai-sdk/anthropic";
import { CrewLayerClient } from "crewlayer";
import {
  crewLayerMemory,
  crewLayerTools,
  CrewLayerDataStream,
} from "crewlayer/integrations/vercel-ai";

// ── Clients are created once at module level (reused across requests) ─────────
const crewlayer = new CrewLayerClient({
  apiKey: process.env.CREWLAYER_API_KEY!,
  baseUrl: process.env.CREWLAYER_URL ?? "http://localhost:8000",
});

const AGENT_ID = process.env.CREWLAYER_AGENT_ID!;

const memory = crewLayerMemory({
  client: crewlayer,
  agentId: AGENT_ID,
  memoryLimit: 6,   // prepend up to 6 recalled memories as context
});

const tools = crewLayerTools({
  client: crewlayer,
  agentId: AGENT_ID,
});

// ── Route handler ─────────────────────────────────────────────────────────────
export async function POST(req: Request): Promise<Response> {
  const body = await req.json() as { messages: unknown[]; sessionId?: string };
  const { messages, sessionId = "default" } = body;

  // Validate — CoreMessage[]
  if (!Array.isArray(messages) || messages.length === 0) {
    return Response.json({ error: "messages array is required" }, { status: 400 });
  }

  // 1. Fetch relevant long-term memories and prepend as a system message
  //    e.g. "Relevant memories:\n- User prefers Python\n- User is building a RAG pipeline"
  const contextMessages = await memory.get(messages as never[]);

  // 2. Stream the LLM response
  //    The model has access to recall_memory, log_action, read_context, write_context
  const result = streamText({
    model: anthropic("claude-opus-4-8"),
    system: "You are a helpful AI assistant with persistent memory. " +
            "Use the recall_memory tool when you need to remember past conversations.",
    messages: [...contextMessages, ...(messages as never[])] as never[],
    tools: {
      recall_memory: tools.recall_memory as never,
      write_context: tools.write_context as never,
    },
    maxSteps: 3,   // allow up to 3 tool calls per turn
  });

  // 3. Persist the incoming messages (non-blocking — don't await)
  void memory.update({ messages: messages as never[] });

  // 4. Wrap the text stream — logs a "vercel.stream" action on completion
  return new CrewLayerDataStream(result.textStream, {
    client: crewlayer,
    agentId: AGENT_ID,
    sessionId,
    toolName: "chat.completion",
  }).toResponse();
}
