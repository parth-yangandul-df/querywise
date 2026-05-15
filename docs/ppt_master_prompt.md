# QueryWise — PPT Master Prompt

---

You are an expert presentation designer. Create a complete, professional PowerPoint presentation for the **QueryWise** project using the slide-by-slide content provided below.

## Project Summary

**QueryWise** is a natural-language-to-SQL chatbot built for the company's internal **Project & Resource Management System (PRMS)**. PRMS is a comprehensive dashboard that tracks resources, clients, projects, and timesheets — containing dozens of tables, hundreds of columns, and countless metrics. While the system provides rich data, finding specific information requires navigating multiple menus, clicking through various tabs, and memorizing where each piece of data lives.

**The Problem:** The PRMS dashboard is powerful but complex. When users need specific data — like "which projects are over budget" or "who is available next month" — they must manually click through 5-10 different screens, apply multiple filters, export data to Excel, and piece together information manually. This is time-consuming, exhausting, and often frustrating when users can't find what they need. The data exists — but it's hidden behind too many clicks.

**The Solution:** QueryWise lets users simply ask questions in plain English. The system uses **agentic AI** powered by **LangGraph** to understand the question, find the right tables, generate the correct SQL query, execute it, and return the answer — all without any technical knowledge required.

This presentation showcases how agentic AI and LangGraph work in practice, designed for:
1. **Non-technical audiences** — business users, managers, executives
2. **Future developers** — anyone wanting to learn or build with agentic AI and LangGraph

---

## Understanding Agentic AI

### What is Agentic AI?

Think of agentic AI like a **team of specialists** working together to solve a complex problem. Instead of asking one person to do everything, you have multiple experts — each skilled at a specific task — who collaborate, check each other's work, and help when something goes wrong.

**Simple analogy — The Restaurant Kitchen:**

Imagine you're at a restaurant. You order a complex meal. What happens in the kitchen?

- The **head chef** decides what goes on the plate
- The **sous chef** prepares each component
- The **line cook** cooks the actual food
- The **plater** arranges everything beautifully
- The **quality checker** tastes and approves before it goes out

No one person does everything. Each specialist does their job, passes it to the next person, and the final result is much better than if one person tried to do it all.

Agentic AI works the same way — multiple AI "specialists" collaborate to get better results than any single AI could achieve alone.

### Why Use Agentic AI for QueryWise?

Traditional text-to-SQL systems use a single AI to handle everything at once. This is like one person trying to be the chef, sous chef, cook, plater, and checker all at the same time. It often leads to:

1. **Mistakes** — The AI guesses table names and column meanings instead of knowing them
2. **No recovery** — When something goes wrong, there's no "expert" to fix it
3. **No context** — Generic AI doesn't understand company-specific terms like "active client" or "utilization rate"
4. **No validation** — Bad SQL gets executed, wasting time and potentially causing issues

QueryWise solves this by having **specialized AI agents** that:
- Focus on one task each (generate SQL, check SQL, fix errors, explain results)
- Pass work to each other like a relay race
- Automatically fix mistakes without bothering the user
- Have access to business context so they understand company terminology

### Traditional vs Agentic Approach

| Traditional (One AI) | QueryWise (Team of AIs) |
|---------------------|--------------------------|
| Single AI does everything | Multiple AI specialists, each doing one thing well |
| Guesses table/column names | Knows exact table/column names from semantic layer |
| No error recovery | Automatically fixes errors and retries |
| Generic terminology | Understands company-specific terms |
| No validation | Checks SQL before execution |
| All or nothing | Fast path for simple queries, full power for complex |

---

## Slide Design Rules

Apply these rules to every slide:

- **Maximum 5 bullet points per slide** — split content across multiple slides rather than overcrowding
- **No paragraphs** — only concise, scannable bullet points
- **Minimal and clean** — clarity over completeness on any single slide
- **No redundancy** — each slide covers unique ground; no repeated information
- **Simple language** — avoid unnecessary jargon; explain technical concepts plainly
- **Professional tone** — presentation-ready, not documentation
- **Logical flow** — slides build on each other from problem to solution to value
- **Non-technical friendly** — all slides should be understandable by business users with no AI/technical background

---

## Required Slide Structure

Create exactly **17 slides** in order. Each slide must include a **title**, **bullet points**, and **speaker notes**.

---

### Slide 1: Title Slide

**Title:** QueryWise: Agentic AI for Natural Language to SQL

**Subtitle:** Powered by LangGraph — A Multi-Agent System for Accurate Database Queries

**Speaker Notes:**
Welcome to the QueryWise presentation. Today we'll showcase how we're using **agentic AI** — specifically LangGraph — to revolutionize how business users query databases. QueryWise isn't just another text-to-SQL tool; it's a coordinated team of specialized AI agents that work together to transform natural language questions into accurate, safe SQL queries.

---

### Slide 2: Problem Statement

**Title:** The Problem: Data Hidden in a Complex Dashboard

**Bullet Points:**
- PRMS dashboard has **dozens of tables, hundreds of columns**, and endless menus
- Finding answers like "Which projects are over budget?" requires clicking through **5-10 different screens**
- Users must apply filters, export to Excel, and manually piece together information
- The average user spends **5-10 minutes per query** just navigating the dashboard
- Writing SQL is not an option — **business users don't have technical skills**

**Speaker Notes:**
Imagine you're a project manager and you need to answer: "Which of my projects are over budget this month?" In the PRMS dashboard, you'd need to: open the projects tab, filter by your projects, find the budget column, cross-reference with actual costs, check completion status, and maybe export to Excel to compare. This takes 5-10 minutes of clicking. Now imagine doing this 20 times a day. That's the reality for many users. The data exists — it's just hidden behind too many clicks. QueryWise removes this friction by letting users just ask the question.

---

### Slide 3: Before & After Example

**Title:** See the Difference: Before vs After

**Bullet Points:**
- **Question:** "Which projects are over budget this month?"
- **Before:** Click Projects → Filter → Find columns → Export to Excel → Manually calculate → Answer
- **Time before:** 5-10 minutes of clicking through multiple screens
- **After with QueryWise:** Just ask → Get answer in 5 seconds
- **Another example:** "Who is available next month?" — from 5+ clicks to instant answer

**Speaker Notes:**
Let me show you what this looks like in practice. Take the question "Which projects are over budget this month?" Before QueryWise, you'd click through the projects tab, filter to your projects, find the budget columns, cross-reference with actual costs, maybe export to Excel to manually calculate. This takes 5-10 minutes. With QueryWise, you just type the question and get the answer in 5 seconds. Same for "Who is available next month?" Instead of clicking through resources, availability calendars, and cross-referencing project assignments, you just ask. This isn't just faster — it changes what questions people actually ask. Suddenly, exploring data becomes effortless.

---

### Slide 4: Solution Overview

**Title:** How QueryWise Works: Step by Step

**Bullet Points:**
- **Step 1:** User types a question in plain English
- **Step 2:** System figures out what they're asking
- **Step 3:** System finds the right tables and generates SQL
- **Step 4:** System executes the query and returns the answer
- If something goes wrong, the system automatically tries to fix it

**Speaker Notes:**
Here's how QueryWise works, step by step. Step one: you type a question. Step two: the system figures out what you're asking — are you asking about resources? Clients? Projects? Step three: it looks up what tables and columns contain that information and generates the SQL query. Step four: it runs the query and takes the raw results and turns them into a clear answer. And if anything goes wrong, the system automatically tries to fix it. The user never sees any of this — they just get their answer.

---

### Slide 5: LangGraph — The Traffic Controller

**Title:** How AI Agents Work Together: The Traffic Controller Analogy

**Bullet Points:**
- **The problem:** Multiple AI agents need to work together without getting in each other's way
- **The solution:** LangGraph acts like an air traffic controller — it directs each agent when to act and passes their results to the next step
- **Think of it this way:**
  - Question arrives → Intent classifier decides "This is a project question"
  - LangGraph routes to the Project Expert → Gets SQL
  - LangGraph routes to the Validator → Checks the SQL
  - If valid → LangGraph routes to Executor → Runs query
  - If invalid → LangGraph routes back to fix the problem
- Each "arrow" in the flow is LangGraph making sure nothing falls through the cracks

**Speaker Notes:**
You might wonder — how do all these AI agents work together without stepping on each other's toes? The answer is **LangGraph**. Think of LangGraph as an air traffic controller. When planes (AI agents) are on the ground, the controller decides which one takes off, when to taxi, and when to land. In our system, LangGraph is that controller. It decides when the QueryComposer writes SQL, passes that SQL to the Validator, and if it's good, sends it to the Executor. If it's bad, LangGraph routes it back to fix the problem. Each arrow in our flowchart — each transition from one agent to the next — is LangGraph doing its job. It's what makes the whole system feel like one cohesive unit rather than a bunch of disconnected parts.

---

### Slide 6: Agentic AI Architecture

**Title:** Meet the AI Team

**Bullet Points:**
- **QueryComposer:** The main writer — turns questions into SQL
- **SQLValidator:** The checker — makes sure SQL is safe and correct
- **ErrorHandler:** The problem-solver — fixes mistakes automatically
- **ResultInterpreter:** The translator — turns results into plain English
- Plus 5 domain experts for fast answers on common questions

**Speaker Notes:**
Think of our system as a team with different roles. The QueryComposer does the heavy lifting — taking a question and writing the SQL query. The SQLValidator is like an editor, checking that the SQL is safe and makes sense. The ErrorHandler is the troubleshooter — if something goes wrong, this agent figures out what to fix. The ResultInterpreter takes the raw database results and turns them into something a human can understand. And we also have 5 domain experts who know the answers to common questions without needing AI at all — that's our fast path.

---

### Slide 7: The Semantic Layer

**Title:** Why the AI Knows the Right Answers

**Bullet Points:**
- **Glossary:** "Active client" means X, Y, Z — exact definitions, not guesses
- **Metrics:** How to calculate utilization rate, revenue, ECL
- **Data Dictionary:** What each column actually means (code → label)
- **Knowledge:** Company policies, rules, and reference material
- All of this is stored and searched intelligently

**Speaker Notes:**
You might wonder — how does the AI know what "active client" means? How does it know which columns to use? The answer is the **semantic layer**. Before we even answer any questions, we build a knowledge base of business terms, metrics, and rules. When someone asks "show me active clients," the system looks up exactly what "active client" means in our context. No guessing. No hallucination. Just accurate answers because the AI has been taught the business definitions.

---

### Slide 8: LangGraph Pipeline Deep Dive

**Title:** How the AI Team Works Together

**Bullet Points:**
- **Two paths:** Simple questions get fast answers; complex questions get full AI treatment
- **Fast path:** Common questions like "show active clients" → instant SQL templates
- **Full path:** Complex questions → AI writes custom SQL with business context
- **Smart routing:** The system decides which path based on confidence level
- **State flows:** Each step passes its work to the next — nothing is lost

**Speaker Notes:**
We've talked about the team members. Now let's see how they work together. The system has two paths. For simple, common questions like "show me active clients," we skip the AI entirely and use pre-built templates — it's instant. For more complex questions, the full AI team kicks in. How does it decide? It calculates a confidence score. High confidence means fast path. Low confidence means full AI path. And LangGraph makes sure each team member passes their work to the next — the SQL writer passes to the checker, who passes to the executor, who passes to the translator. No dropped balls.

---

### Slide 9: The Four LLM Agents

**Title:** What Each AI Team Member Does

**Bullet Points:**
- **QueryComposer:** Takes the question + business context → writes SQL
- **SQLValidator:** Checks the SQL is safe and will work
- **ErrorHandler:** If something breaks, fixes it and tries again (up to 3 times)
- **ResultInterpreter:** Turns raw database results into a clear answer

**Speaker Notes:**
Each agent on our team has one job. The QueryComposer is the main writer. The SQLValidator is the proofreader. The ErrorHandler is the fixer — if the database says there's an error, this agent analyzes it, figures out what went wrong, and tries a corrected version. Up to 3 times. Finally, the ResultInterpreter takes whatever the database returns — rows and columns — and turns it into sentences the user can understand.

---

### Slide 10: Domain Agents

**Title:** The Fast Path: Common Questions Get Instant Answers

**Bullet Points:**
- **Resource expert:** "Who is available?" — knows availability queries cold
- **Client expert:** "Show active clients" — instant answers on client data
- **Project expert:** "What are my project budgets?" — knows project queries
- **Timesheet expert:** "What needs approval?" — handles timesheet questions
- **Self-service:** "What's my utilization?" — personal queries answered instantly

**Speaker Notes:**
In addition to the AI team, we have 5 domain experts. These are specialists who know the answers to common questions without needing AI at all. "Show me active clients" doesn't need to go through the full AI pipeline — the client expert already knows the SQL for that. Same for resource availability, project budgets, timesheets, and your own personal data. This makes common queries nearly instant. And if a question is too complex, it seamlessly escalates to the full AI team.

---

### Slide 11: Intent Classification

**Title:** How the System Knows What You Mean

**Bullet Points:**
- The system recognizes 24 different types of questions
- Each question gets a "confidence score" — how sure the system is
- High confidence (>80%) = use the fast template path
- Low confidence (<80%) = escalate to full AI for custom SQL
- Example: "Who is available?" → 95% confidence (fast) vs "Show me trends" → 60% confidence (AI)

**Speaker Notes:**
How does the system know what you're asking? We built an **intent classifier** that recognizes 24 types of questions. When you type something, it calculates a confidence score — how sure it is about what you mean. If it's very confident, like "who is available," it uses the fast template path. If it's less confident, like "show me trends," it sends it to the AI team for a custom SQL query. This hybrid approach gives us both speed for simple questions and flexibility for complex ones.

---

### Slide 12: Query Pipeline Flow

**Title:** The Complete Flow: Question to Answer

**Bullet Points:**
- **Step 1:** User asks in plain English
- **Step 2:** System figures out what they're asking (intent classification)
- **Step 3:** System finds the right tables and writes SQL (or uses template)
- **Step 4:** System checks the SQL is safe
- **Step 5:** System runs the SQL against the database
- **Step 6:** If it fails, system tries to fix it automatically (up to 3 times)
- **Step 7:** System turns results into a clear answer

**Speaker Notes:**
Let's walk through the full journey. You type a question. The system figures out what you mean — intent classification. It then writes the SQL, either from a template or custom. Then it checks that the SQL is safe. Then it runs it against the database. If the database says there's an error, the ErrorHandler automatically tries to fix it and retry — up to 3 times. Finally, the ResultInterpreter takes the raw database results and turns them into a clear answer you can understand. All of this happens in seconds.

---

### Slide 13: Tech Stack

**Title:** How It's Built: The Technology

**Bullet Points:**
- **Backend:** Python + FastAPI + LangGraph — modern, fast, reliable
- **Frontend:** React — clean, responsive interface
- **Database:** PostgreSQL with vector search for semantic layer
- **AI:** Works with Anthropic, OpenAI, Ollama, or Groq — your choice
- **Deployment:** Docker — one command starts everything

**Speaker Notes:**
What's under the hood? We use Python with FastAPI for the backend — it's modern, fast, and well-supported. The frontend uses React for a clean interface. PostgreSQL stores our semantic layer and handles vector search for intelligent matching. For AI, we're provider-agnostic — you can use Anthropic Claude, OpenAI, Ollama, or Groq. And everything runs in Docker, so starting the system is as simple as one command.

---

### Slide 14: Use Cases

**Title:** What You Can Ask

**Bullet Points:**
- "Who is available for a new project next month?"
- "Show me all active clients and their project status"
- "Which projects are over budget or behind schedule?"
- "What timesheets are pending approval this week?"
- "What's my current project allocation and utilization?"

**Speaker Notes:**
Here are real examples of what you can ask. Resource managers: "who is available next month?" Project leads: "which projects are over budget?" Finance: "what needs approval this week?" And for everyone: "what's my utilization?" These are the kinds of questions that would normally take minutes of clicking through the dashboard — now you just ask.

---

### Slide 15: Safety & Reliability

**Title:** Built-In Safety and Reliability

**Bullet Points:**
- **Double protection:** Blocklist of dangerous commands + read-only database access
- **Automatic fixes:** If something breaks, the system tries to fix it (up to 3 times)
- **Limits:** Max 1,000 rows per query, 30-second timeout — nothing runs forever
- **Non-blocking:** Embeddings happen in background, never slow down your query
- **Audit trail:** Every query logged for compliance

**Speaker Notes:**
We didn't just build features — we built safety. First, there's a blocklist that stops dangerous commands, and the database connection is read-only so nothing can be modified. Second, if something goes wrong, the ErrorHandler tries to fix it automatically — up to 3 times. Third, we have limits so queries don't overwhelm the system. And everything is logged for compliance. This is enterprise-grade reliability.

---

### Slide 16: Future Scope

**Title:** What's Coming Next

**Bullet Points:**
- **Access control:** Different people see different data based on their role
- **More areas:** HR, finance, sales, and operations — all coming online
- **Multi-language:** Ask in Spanish, French, German — and get answered in kind
- **Smarter insights:** Trend detection, anomaly alerts, forecasting
- **Integrations:** Right in Slack, Teams, or your company portal

**Speaker Notes:**
QueryWise is a foundation, not a finished product. We're adding role-based access control so different people see different data. New domain experts for HR, finance, sales. Multi-language support so you can ask in any language. Advanced analytics that don't just answer questions but surface trends and anomalies. And integrations so you can use QueryWise right where you already work — Slack, Teams, your company portal. The agentic architecture makes adding all of this straightforward.

---

### Slide 17: Conclusion

**Title:** The Bottom Line

**Bullet Points:**
- **Team approach:** Multiple AI specialists work together, not one AI doing everything
- **Business context:** The semantic layer means accurate answers, not guesses
- **Automatic fixes:** When things go wrong, the system fixes itself — you never see errors
- **Safe and reliable:** Enterprise-grade protection built in
- **Just ask:** Questions in plain English. Answers in seconds.

**Speaker Notes:**
Here's what makes QueryWise different. Instead of one AI that might get it right or wrong, we have a team — specialized agents that check, validate, and correct each other. The semantic layer means they understand our business, not just generic patterns. The ErrorHandler means when something goes wrong, it gets fixed automatically. It's safe, reliable, and designed for everyone. Just ask your question in plain English — get your answer in seconds. Thank you.

---

## Output Format Requirements

- Produce exactly **17 slides** in the order specified above
- Each slide must have a **clear title**, **bullet points** (max 5), and **speaker notes**
- Use a **clean, professional design** with consistent typography and spacing
- Include a **visual element suggestion** for each slide (e.g., icon, diagram placeholder, chart type)
- Maintain a **coherent visual theme** throughout the presentation
- Ensure **no content redundancy** — each slide covers unique information
- The final output should be **presentation-ready** with no major edits needed
- **Main Highlight:** Emphasize agentic AI and LangGraph throughout — this is the primary differentiator to showcase

(End of file - total 305 lines)