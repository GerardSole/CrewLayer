# CrewLayer TypeScript SDK

Official TypeScript/JavaScript SDK for the [CrewLayer](https://github.com/crewlayer/crewlayer) AI agent backend.

Works in **Node.js 18+** and **modern browsers** (uses native `fetch` — no axios or httpx).

## Install

```bash
npm install crewlayer
# or
yarn add crewlayer
# or
pnpm add crewlayer
```

## Quick start

```typescript
import { CrewLayerClient } from "crewlayer";

const client = new CrewLayerClient({
  apiKey: "crwl_...",              // or set CREWLAYER_API_KEY env var
  baseUrl: "http://localhost:8000", // default
});

// Append a message to short-term memory
await client.memory.append({
  agentId: "agent-001",
  sessionId: "sess-001",
  role: "user",
  content: "Hola, recuerda que prefiero el modo oscuro",
});

// Semantic search over long-term memories
const result = await client.memory.recall({
  agentId: "agent-001",
  query: "preferencias de UI",
  limit: 5,
  minSimilarity: 0.7,
});
console.log(result.results); // MemoryItem[]

// Subscribe to real-time context updates (SSE)
const stream = client.context.subscribe({ namespace: "proyecto:xyz", key: "status" });
stream.on("updated", (entry) => console.log("updated:", entry.value));
stream.on("deleted", ({ key }) => console.log("deleted:", key));
stream.on("error", (err) => console.error(err));
// Later:
stream.close();
```

## Configuration

```typescript
const client = new CrewLayerClient({
  apiKey: "crwl_...",   // Required (or CREWLAYER_API_KEY env var in Node.js)
  baseUrl: "https://your-crewlayer-instance.com",
  maxRetries: 3,        // Retries on 5xx: 1s, 2s, 4s backoff (default: 3)
  timeout: 30_000,      // Request timeout in ms (default: 30 000)
});
```

## API Reference

### `client.memory`

```typescript
// Append a message to short-term memory (stored in Redis)
const mem = await client.memory.append({
  agentId: "agent-001",
  sessionId: "sess-001",
  role: "user",           // "user" | "assistant" | "system" | "tool"
  content: "Hello",
  metadata: {},           // optional
});

// Read short-term message history
const history = await client.memory.messages({ agentId: "agent-001", sessionId: "sess-001" });

// Semantic recall from long-term memory
const recall = await client.memory.recall({
  agentId: "agent-001",
  query: "user preferences",
  limit: 10,            // default: 5
  minSimilarity: 0.7,   // cosine threshold (default: 0.6)
  tags: ["preference"],
});

// Extract facts from a session into long-term memory (calls Claude)
const extracted = await client.memory.extract({
  agentId: "agent-001",
  sessionId: "sess-001",
  minImportance: 0.5,   // optional filter
});
console.log(`Extracted ${extracted.extractedCount} memories`);

// List long-term memories
const page = await client.memory.list({
  agentId: "agent-001",
  limit: 20,
  page: 1,
  includeArchived: false,
  tags: ["preference"],
});

// Memory stats
const stats = await client.memory.stats("agent-001");
console.log(stats.activeMemories, stats.avgImportance);

// Delete a memory
await client.memory.delete({ agentId: "agent-001", memoryId: "mem-001" });
```

### `client.actions`

```typescript
// Log an agent action
const action = await client.actions.log({
  agentId: "agent-001",
  toolName: "web_search",
  inputParams: { query: "TypeScript types" },
  outputResult: { count: 5, results: ["..."] },
  status: "success",      // "success" | "error" | "running"
  sessionId: "sess-001",
  durationMs: 120,
});

// Retrieve a specific action
const act = await client.actions.get("agent-001", "act-001");

// List actions with filters
const page = await client.actions.list({
  agentId: "agent-001",
  status: "error",
  toolName: "web_search",
  limit: 50,
  cursor: page.nextCursor, // cursor pagination
});

// Aggregate stats by tool
const stats = await client.actions.stats("agent-001");
stats.byTool.forEach(({ toolName, count, errorRate }) =>
  console.log(toolName, count, `${(errorRate * 100).toFixed(1)}% errors`)
);
```

### `client.context`

The context blackboard is a shared key/value store with namespacing, versioning and immutable history.

```typescript
// Write a value
const entry = await client.context.write({
  namespace: "project:abc",
  key: "phase",
  value: { stage: "planning", progress: 0 },
  writtenBy: "agent-001",
  expectedVersion: 0,    // optimistic locking; 0 = key must not exist yet
});
console.log(entry.version); // 1

// Read a value
const current = await client.context.read({ namespace: "project:abc", key: "phase" });

// List all keys in a namespace
const ns = await client.context.listNamespace({ namespace: "project:abc" });

// Delete a key
await client.context.delete({ namespace: "project:abc", key: "phase" });

// History (immutable log)
const history = await client.context.history({
  namespace: "project:abc",
  key: "phase",
  limit: 20,
});

// Point-in-time lookup
const v1 = await client.context.historyAt({ namespace: "project:abc", key: "phase", version: 1 });

// Rollback to a previous version
const restored = await client.context.rollback({
  namespace: "project:abc",
  key: "phase",
  version: 1,
});

// Real-time subscription (SSE)
const stream = client.context.subscribe({ namespace: "project:abc", key: "phase" });
stream
  .on("updated", (entry) => console.log("new value:", entry.value))
  .on("deleted", ({ key }) => console.log("deleted:", key))
  .on("close", () => console.log("connection closed"));
// Stop listening:
stream.close();
```

### `client.agents`

```typescript
// Create an agent
const agent = await client.agents.create({
  name: "Research Bot",
  description: "Searches and summarizes documents",
  config: { model: "claude-opus-4-8" },
  tags: ["research", "production"],
});

// List agents
const page = await client.agents.list({ status: "idle", tags: ["research"] });

// Get, update, delete
const a = await client.agents.get(agent.id);
const updated = await client.agents.update(agent.id, { description: "Updated" });
await client.agents.delete(agent.id);

// Status
const status = await client.agents.getStatus(agent.id);
await client.agents.setStatus({ agentId: agent.id, status: "working", sessionId: "sess-001" });

// Tags
await client.agents.addTags(agent.id, ["v2"]);
await client.agents.removeTag(agent.id, "v1");
const allTags = await client.agents.listTags();

// Agent hierarchy relations
await client.agents.setRelation({ agentId: "supervisor-id", targetId: "worker-id", relationType: "supervisor" });
const relations = await client.agents.listRelations("supervisor-id");
const tree = await client.agents.getTree("supervisor-id");
await client.agents.deleteRelation("supervisor-id", "worker-id");

// Export / import (portability)
const snapshot = await client.agents.export(agent.id);
const imported = await client.agents.import(snapshot);
console.log("New agent ID:", imported.agent.id);
console.log("ID map:", imported.idMap);
console.log("Warnings:", imported.warnings);
```

### `client.sessions`

```typescript
// Create a session
const session = await client.sessions.create({
  agentId: "agent-001",
  episodeId: "ep-001",  // optional
});

// Get, list, close
const s = await client.sessions.get(session.id);
const page = await client.sessions.list({ agentId: "agent-001", status: "active" });
const closed = await client.sessions.close(session.id);

// Assign to an episode
await client.sessions.update({ sessionId: session.id, episodeId: "ep-002" });
```

### `client.episodes`

Episodes group related sessions and memories under a named task (e.g. "debug memory leak", "onboard user X").

```typescript
// Create an episode
const ep = await client.episodes.create({
  agentId: "agent-001",
  title: "Memory leak investigation",
  description: "Track debugging progress",
});

// List episodes
const page = await client.episodes.list({ agentId: "agent-001", status: "active" });

// Get detail (with linked sessions + memories)
const detail = await client.episodes.get("agent-001", ep.id);
console.log(detail.sessions, detail.memories);

// Complete (triggers Claude summary generation)
const completed = await client.episodes.complete("agent-001", ep.id);
console.log(completed.summary);

// Semantic recall scoped to this episode
const memories = await client.episodes.recall({
  agentId: "agent-001",
  episodeId: ep.id,
  query: "root cause",
  limit: 5,
});
```

## Error handling

```typescript
import { CrewLayerError, AuthError, NotFoundError, RateLimitError } from "crewlayer";

try {
  await client.agents.get("missing-id");
} catch (err) {
  if (err instanceof NotFoundError) {
    console.log("agent does not exist");
  } else if (err instanceof AuthError) {
    console.log("check your API key");
  } else if (err instanceof RateLimitError) {
    console.log("slow down");
  } else if (err instanceof CrewLayerError) {
    console.log(`HTTP ${err.status}:`, err.message);
  }
}
```

| Class | Status | Description |
|---|---|---|
| `CrewLayerError` | — | Base class for all SDK errors |
| `AuthError` | 401/403 | Invalid or missing API key |
| `NotFoundError` | 404 | Resource does not exist |
| `ConflictError` | 409 | Version conflict or duplicate |
| `RateLimitError` | 429 | API key quota exceeded |
| `ServerError` | 5xx | Internal server error |

## SSE streaming

`client.context.subscribe()` returns a `ContextSSEStream` — a lightweight EventEmitter that works in both Node.js and browsers:

```typescript
const stream = client.context.subscribe({ namespace: "project:abc", key: "status" });

stream
  .on("updated", (entry: ContextEntry) => { /* ... */ })
  .on("deleted", ({ key }) => { /* ... */ })
  .on("error", (err: Error) => { /* ... */ })
  .on("close", () => { /* connection closed or stream.close() called */ });

// Unsubscribe a specific handler
stream.off("updated", myHandler);

// Close the connection
stream.close();
```

## Build output

Running `npm run build` produces:

```
dist/
├── index.js      # ESM
├── index.cjs     # CommonJS
├── index.d.ts    # TypeScript declarations
└── *.map         # Source maps
```

## Integrations

### Vercel AI SDK / Next.js

```bash
npm install crewlayer ai @ai-sdk/anthropic
```

Three adapters available from `crewlayer/integrations/vercel-ai`:

| Export | What it does |
|---|---|
| `crewLayerMemory()` | Memory provider — prepends recalled memories before LLM calls, persists messages after |
| `crewLayerTools()` | Four LLM-callable tools: `recall_memory`, `log_action`, `read_context`, `write_context` |
| `CrewLayerDataStream` | Wraps `result.textStream`, auto-logs the completed response as a CrewLayer action |

**Full route handler example:**

```typescript
// app/api/chat/route.ts
import { streamText } from "ai";
import { anthropic } from "@ai-sdk/anthropic";
import { CrewLayerClient } from "crewlayer";
import {
  crewLayerMemory,
  crewLayerTools,
  CrewLayerDataStream,
} from "crewlayer/integrations/vercel-ai";

const client = new CrewLayerClient({ apiKey: process.env.CREWLAYER_API_KEY! });
const AGENT_ID = process.env.CREWLAYER_AGENT_ID!;

const memory = crewLayerMemory({ client, agentId: AGENT_ID, memoryLimit: 8 });
const tools  = crewLayerTools({ client, agentId: AGENT_ID });

export async function POST(req: Request) {
  const { messages, sessionId = "default" } = await req.json();

  // 1. Prepend relevant long-term memories as a system message
  const contextMessages = await memory.get(messages);

  // 2. Stream the LLM response with CrewLayer tools available
  const result = streamText({
    model: anthropic("claude-opus-4-8"),
    messages: [...contextMessages, ...messages],
    tools: {
      recall_memory: tools.recall_memory,
      write_context:  tools.write_context,
    },
  });

  // 3. Persist the conversation to short-term memory (non-blocking)
  void memory.update({ messages });

  // 4. Wrap the text stream — logs the completed response as an action
  return new CrewLayerDataStream(result.textStream, {
    client,
    agentId: AGENT_ID,
    sessionId,
  }).toResponse();
}
```

**Memory-only usage** (no tools, no streaming wrapper):

```typescript
const memory = crewLayerMemory({ client, agentId: "agent-001", sessionId: "sess-001" });

// Before the LLM call — returns [] if no relevant memories
const context = await memory.get(messages);

// After the LLM call — persists new messages
await memory.update({ messages: [...messages, assistantReply] });

// Fetch raw session history as CoreMessage[]
const history = await memory.getMessages();

// Save a batch of messages explicitly
await memory.saveMessages({ messages, sessionId: "sess-002" });
```

**Tools without streaming:**

```typescript
import { generateText, jsonSchema } from "ai";
import { crewLayerTools } from "crewlayer/integrations/vercel-ai";

const tools = crewLayerTools({ client, agentId: "agent-001" });

// Tools use plain JSON Schema — wrap with jsonSchema() if needed by your SDK version
const result = await generateText({
  model: anthropic("claude-opus-4-8"),
  messages,
  tools: {
    recall_memory: {
      ...tools.recall_memory,
      parameters: jsonSchema(tools.recall_memory.parameters),
    },
    read_context: {
      ...tools.read_context,
      parameters: jsonSchema(tools.read_context.parameters),
    },
  },
});
```

**Manual stream logging:**

```typescript
import { CrewLayerDataStream } from "crewlayer/integrations/vercel-ai";

const stream = new CrewLayerDataStream(result.textStream, {
  client,
  agentId: "agent-001",
  sessionId: "sess-001",
  toolName: "chat.completion",   // custom action name (default: "vercel.stream")
});

// Consume directly (logs on completion)
for await (const chunk of stream) {
  process.stdout.write(chunk);
}

// Or return as a Next.js streaming response
return stream.toResponse({ status: 200 });
```

## Development

```bash
npm install
npm test          # vitest run
npm run typecheck # tsc --noEmit
npm run build     # tsup
```
