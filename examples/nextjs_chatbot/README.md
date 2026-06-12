# CrewLayer × Next.js Chatbot

Streaming chatbot with persistent memory powered by CrewLayer and the Vercel AI SDK.

Every conversation is remembered across sessions — the model recalls relevant facts
from previous chats before each response.

## What's included

```
app/api/chat/route.ts   — streaming route handler (the only file you need)
```

## Setup

### 1. Create a Next.js app

```bash
npx create-next-app@latest my-chatbot --typescript --app
cd my-chatbot
```

### 2. Install dependencies

```bash
npm install crewlayer ai @ai-sdk/anthropic
```

### 3. Copy the route handler

```bash
mkdir -p app/api/chat
cp <crewlayer-repo>/examples/nextjs_chatbot/app/api/chat/route.ts app/api/chat/route.ts
```

### 4. Set environment variables

Create `.env.local`:

```bash
CREWLAYER_API_KEY=crwl_...
CREWLAYER_AGENT_ID=<your-agent-uuid>
CREWLAYER_URL=http://localhost:8000   # or your deployed CrewLayer instance
ANTHROPIC_API_KEY=sk-ant-...
```

### 5. Start CrewLayer (if running locally)

```bash
# From the CrewLayer repo root:
docker compose up -d
alembic upgrade head
uvicorn main:app --reload
```

### 6. Run the dev server

```bash
npm run dev
```

### 7. Test the API

```bash
curl -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "My name is Alex and I prefer Python."}
    ],
    "sessionId": "test-session"
  }'
```

Run it a second time with a different question — the model will remember your name
and preferences from the previous message.

```bash
curl -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "What do you know about me?"}
    ],
    "sessionId": "test-session-2"
  }'
```

## How memory works

```
User message
      │
      ▼
crewLayerMemory.get()   ← semantic recall from PostgreSQL/pgvector
      │                    returns: "Relevant memories:\n- User prefers Python..."
      ▼
streamText({ messages: [recalled_context, ...user_messages] })
      │
      ▼
CrewLayerDataStream     ← streams response, logs "chat.completion" action on finish
      │
      ▼
crewLayerMemory.update() ← persists new messages to Redis session store (async)
```

## Adding a simple chat UI

In `app/page.tsx`:

```tsx
"use client";
import { useChat } from "ai/react";

export default function Chat() {
  const { messages, input, handleInputChange, handleSubmit } = useChat({
    api: "/api/chat",
    body: { sessionId: "my-session" },
  });

  return (
    <div style={{ maxWidth: 600, margin: "40px auto", fontFamily: "sans-serif" }}>
      <div style={{ height: 400, overflowY: "auto", border: "1px solid #ddd", padding: 16, marginBottom: 16 }}>
        {messages.map(m => (
          <div key={m.id} style={{ marginBottom: 12 }}>
            <strong>{m.role === "user" ? "You" : "AI"}:</strong> {m.content}
          </div>
        ))}
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="Type a message..."
          style={{ flex: 1, padding: 8 }}
        />
        <button type="submit" style={{ padding: "8px 16px" }}>Send</button>
      </form>
    </div>
  );
}
```
