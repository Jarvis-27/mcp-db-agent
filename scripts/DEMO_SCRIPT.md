# MCP Database Agent — Video Demo Script

**Total Duration:** ~8–10 minutes
**Format:** Screen recording with voiceover narration
**Prerequisite Setup:** Run `uv sync`, start the Postgres demo database with `docker compose -f docker-compose.demo.yml up -d`, then seed it with `uv run scripts/seed_demo_db.py --db-url postgresql://admin:secret@localhost:5432/ecommerce` before recording. Have Claude Desktop open and configured with the MCP server.

---

## ACT 1: THE PROBLEM (0:00 – 1:30)

### What to show on screen
- Open a terminal. Connect to a database with a raw SQL client (e.g., `psql postgresql://admin:secret@localhost:5432/ecommerce`).
- Run `\dt` to show the four tables.
- Run `\d users` to show column definitions.
- Type a deliberately wrong query like `SELECT * FROM user;` (wrong table name) and show the error.
- Then type a correct but complex query: a multi-table JOIN with aggregation. Pause to show its complexity.

### Narration

> "Every company sits on a goldmine of data — customer records, sales figures, product metrics. But here's the problem: only a handful of people in your organization can actually access it.
>
> To get a simple answer — say, 'What were our top-selling products last quarter?' — a product manager has to write a ticket, wait for an analyst, and hope the SQL is right the first time. If it's wrong? Another round trip. Another day lost.
>
> And even for engineers, writing complex SQL is tedious and error-prone. One wrong table name, one missing JOIN condition, and you're staring at cryptic error messages instead of answers.
>
> What if anyone on your team could just *ask* the database a question in plain English — and get an accurate, safe answer back in seconds?"

---

## ACT 2: THE SOLUTION — INTRODUCING MCP DATABASE AGENT (1:30 – 2:30)

### What to show on screen
- Switch to a clean slide or browser tab showing a simple architecture diagram (or draw one live):
  ```
  You (plain English) → MCP Client (Claude Desktop) → MCP DB Agent → Your Database
  ```
- Briefly show the Claude Desktop sidebar with the MCP server connected (the green dot / tool list).

### Narration

> "This is MCP Database Agent — an open-source server that turns a PostgreSQL database into a natural-language endpoint.
>
> It plugs into any MCP-compatible client — Claude Desktop, Cursor, VS Code Copilot — using the Model Context Protocol. You ask a question in English, and the agent introspects your schema, generates safe SQL, validates it, executes it, and returns clean, structured results.
>
> No SQL knowledge required. No new UI to learn. It works inside the tools your team already uses."

---

## ACT 3: LIVE DEMO — BASIC QUERIES (2:30 – 4:30)

### What to show on screen
Open Claude Desktop connected to the MCP server. Run each query one at a time, pausing to highlight the results.

**Query 1 — Simple exploration:**
> "What tables are in this database?"

- Show the `list_tables` tool being called automatically.
- Highlight: it returns table names *and* row counts (users: 500, products: 100, orders: 2,000, order_items: 5,000).

**Query 2 — Plain English to SQL:**
> "Show me the top 5 countries by number of users."

- Show the generated SQL in the response.
- Show the clean JSON result table.
- Point out: "Notice it auto-added a LIMIT — the agent protects against runaway queries."

**Query 3 — Multi-table JOIN:**
> "What are the top 10 best-selling products by total revenue?"

- Show the complex SQL it generated (JOIN across orders, order_items, products).
- Show the results.

### Narration

> "Let me show you this in action. I have a demo e-commerce database — 500 customers, 100 products, 2,000 orders, 5,000 line items. Realistic data.
>
> I'll start simple: 'What tables are in this database?' — instantly, I see every table and its row count. No need to hunt through schemas.
>
> Now let's ask a real business question: 'Top 5 countries by number of users.' Watch — it writes the SQL, validates it, executes it, and returns the answer in under two seconds. And notice: it automatically injected a safety LIMIT clause, even though I didn't ask for one.
>
> Let's go harder: 'Top 10 best-selling products by total revenue.' This requires joining three tables with aggregation and sorting. The kind of query that takes an analyst 10 minutes to write and debug. The agent handles it instantly."

---

## ACT 4: SAFETY & VALIDATION (4:30 – 5:30)

### What to show on screen

**Query 4 — Write-operation attempt:**
> "Delete all users from the database."

- Show the agent's response: it **refuses**. The SQL validator blocks all write operations (DELETE, DROP, UPDATE, INSERT, TRUNCATE).
- Highlight the error message.

**Query 5 — Non-existent table:**
> "Show me all records from the employees table."

- Show the validation catching the non-existent table reference.

### Narration

> "Now, the question every CTO asks: 'Is it safe?'
>
> Watch what happens when I ask it to delete all users. The agent flat-out refuses. It has a three-layer safety system: first, it blocks all write operations — DELETE, DROP, UPDATE, INSERT, TRUNCATE. It's read-only by design.
>
> Second, it validates that every table referenced in the SQL actually exists in your schema. If I ask about an 'employees' table that doesn't exist, it catches that before anything hits the database.
>
> Third, it auto-injects LIMIT clauses on unbounded SELECTs so a careless query can't pull a million rows and crash your connection.
>
> Your production data is protected at every layer."

---

## ACT 5: SELF-CORRECTION (5:30 – 6:30)

### What to show on screen

**Query 6 — Ambiguous / tricky question:**
> "What's the average order value per month in 2024, and how does it compare to 2023?"

- Show the response. Point out the `"attempts"` field in the result.
- If it self-corrected (attempts > 1), highlight that. If not, explain the mechanism verbally.

- Optionally show the `query_history` tool: ask "Show me recent query history" to display the log with attempts and durations.

### Narration

> "Here's where it gets really impressive. LLMs aren't perfect — sometimes the first SQL attempt has a syntax error or uses the wrong function for the database dialect. Most tools would just fail and hand you a cryptic error.
>
> MCP Database Agent has a self-correction loop. If the first SQL fails, it takes the error message, the failed SQL, and the full schema, and sends it back to the LLM for a fix. It retries up to three times, and it learns from each failure.
>
> You can see the attempt count right in the response. And every query — successful or not — is logged with its duration, attempt count, and any errors, so you have full observability into what the agent is doing."

---

## ACT 6: SCHEMA EXPLORATION TOOLS (6:30 – 7:15)

### What to show on screen

**Query 7 — Schema detail:**
> "Describe the orders table."

- Show the `describe_schema` tool response: columns, types, primary keys, foreign keys, sample values.

**Query 8 — Sample data:**
> "Show me 5 sample rows from the products table."

- Show the `get_sample_data` tool response with actual data.

### Narration

> "The agent also exposes schema exploration tools. Ask it to describe any table and you get columns, types, primary keys, foreign key relationships, and even sample values — everything you need to understand your data model at a glance.
>
> You can also pull sample rows instantly. These tools are perfect for onboarding new team members or exploring an unfamiliar database. No documentation needed — the database documents itself."

---

## ACT 7: SETUP & FLEXIBILITY (7:15 – 8:15)

### What to show on screen
- Show the `.env.example` file in an editor. Highlight the key configuration options.
- Show the one-line setup: `uv sync && uv run src/server.py`.
- Show the Claude Desktop config JSON snippet for connecting the MCP server.
- Briefly show the Docker Compose file if it exists, or mention it.

### Narration

> "Setup takes under two minutes. Point it at a PostgreSQL database with a connection string, add your API key, and you're live.
>
> It supports two LLM backends — Anthropic's Claude for production quality, and Groq's Llama for free-tier development and testing. Switch with a single environment variable.
>
> It runs as a standard MCP server, so it plugs into Claude Desktop, Cursor, VS Code — any MCP client. You can run it locally via stdio, or deploy it as an HTTP service with Docker for your whole team.
>
> Every parameter is tunable: query timeouts, row limits, retry counts, model selection. It fits your infrastructure, not the other way around."

---

## ACT 8: CLOSING — THE VALUE PROPOSITION (8:15 – 9:00)

### What to show on screen
- Return to Claude Desktop. Run one final impressive query:
> "Which customers have placed orders in every month of 2024?"

- Show the complex SQL generated (subquery with GROUP BY, HAVING COUNT(DISTINCT month) = 12) and the results.
- End on the results screen.

### Narration

> "Let me leave you with this. This query — 'Which customers ordered every single month of 2024?' — requires a subquery with DISTINCT month counting and a HAVING clause. It's the kind of SQL that senior engineers look up on Stack Overflow.
>
> With MCP Database Agent, anyone on your team gets the answer in seconds.
>
> To recap what you're getting: natural-language database access for your entire team. Production-safe, read-only queries with automatic validation. A self-correcting engine that handles errors gracefully. Full query logging and observability. Support for PostgreSQL. And zero new tools to learn — it works inside the editors and assistants your team already uses.
>
> Stop gatekeeping your data behind SQL expertise. Let your whole team ask questions and get answers."

---

## APPENDIX: RECORDING TIPS

### Pre-recording checklist
1. Run `uv sync` and `uv run scripts/seed_demo_db.py` to create the demo database
2. Verify the MCP server works: `uv run src/server.py` (should start without errors)
3. Configure Claude Desktop with the MCP server entry
4. Test all 8 queries above to make sure they return good results
5. Close unnecessary apps and notifications
6. Set terminal font size to at least 16pt for readability

### Screen layout suggestions
- **Acts 1, 7:** Terminal only (full screen)
- **Act 2:** Architecture diagram (can be a simple slide or whiteboard drawing)
- **Acts 3–6, 8:** Claude Desktop in focus, full screen. Make sure the tool calls and results are visible.

### Pacing tips
- Pause 2–3 seconds after each query result appears so viewers can read it
- Use cursor highlighting or a zoom tool to draw attention to key parts of the response (attempt count, LIMIT injection, error messages)
- Keep narration conversational — you're explaining to a colleague, not reading a spec

### Suggested query variations (if the scripted ones don't produce great results)
- "How many orders were cancelled last month?"
- "What's the most expensive product in each category?"
- "Show me users who have spent more than $1,000 total."
- "What percentage of orders are in each status?"
- "Which product category generates the most revenue?"
