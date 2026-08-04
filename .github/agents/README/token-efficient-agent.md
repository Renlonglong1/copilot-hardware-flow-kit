# Reducing GitHub Copilot Token Usage by 2/3

Below, you'll find two things: a set of concrete setup changes you can make in about 5 minutes to cut your token usage by roughly 2/3, and a set of behavioral shifts — old habits that were smart under the old model but now cost you real tokens. None of it requires painful workflow changes.

*The 43%, 35%, and 63% figures referenced below are concrete measurements from a controlled experiment — same complex task, same environment, three configurations compared on actual token usage and pricing. Not scientific, but as apples-to-apples as I could make it. Your mileage will vary based on your usage patterns, but the direction is clear and the setup cost is minimal.*

---

## ⚡ Quick Start: ~63% Token Reduction in ~3 Minutes

| # | What                                       | Time             | Savings                                                     |
| - | ------------------------------------------ | ---------------- | ----------------------------------------------------------- |
| 1 | Switch to GPT-5.4 + avoid Anthropic models | 1 min            | ~43% vs Opus baseline (measured)                            |
| 2 | Use the custom agent mode files (attached) | 2 min            | ~35% additional vs GPT-5.4 alone (measured)                 |
|   | **Combined**                         | **~3 min** | **~63% measured; up to ~70% with behavioral changes** |

### Step 1: Switch to GPT-5.4 and Avoid Anthropic Models (~1 min)

**Settings → GitHub Copilot → Chat: Model → select `gpt-5.4-xhigh`**

GPT-5.4 is half the per-token price of Opus on inputs ($2.50 vs $5.00/1M tokens), has no cache write fee (Anthropic charges $6.25/1M for cache writes — a cost that doesn't exist with OpenAI models), and costs less on outputs ($15 vs $25/1M). In my experiment, **switching from Opus to GPT-5.4 cut costs by 43% with no apparent loss in capability.** This is the single highest-ROI change you can make.

More broadly, **avoid Anthropic models (Claude Opus, Sonnet, even Haiku) as your default for agent work.** Anthropic's cache write fee is a pricing dimension that simply doesn't exist with OpenAI or Google models, and it adds up fast in long tool-heavy sessions. In my experiment, Anthropic's cache write charges *alone* cost more than half the entire Custom Agent session. Use Opus only as a model of last resort — when you've hit a task where nothing else is getting the job done.

*Why input matters so much:* In agentic Copilot workflows, **input tokens usually dominate total spend** because every internal LLM call resends the full working context — system prompt, conversation history, and tool results. In long sessions, tool output alone can account for roughly **40–73%** of token spend, while output/reasoning is more like **27–51%**. Cached input is cheaper than raw input, but it still matters a lot because it applies to the same repeated base context on **every turn**. When you have dozens or hundreds of internal model calls, even a low cached-token rate compounds into real money — which is why cutting request count, shrinking context, and avoiding expensive cache-write pricing can matter just as much as lowering the headline input/output rate.

*Why not GPT-5.5?* GPT-5.4 is half the cost of GPT-5.5 on every pricing dimension and proved fully capable. Use 5.5 only if 5.4 isn't cutting it on a specific task.

*Which model is "best"?* That depends on the task. For subjective capability rankings, check out [lmarena.ai](https://lmarena.ai) (formerly Chatbot Arena). For price-vs-performance benchmarks, [artificialanalysis.ai](https://artificialanalysis.ai) is excellent. Both are useful for making informed model choices as new models drop.

### Step 2: Use the Custom Agent Mode for Complex Tasks (~2 min)

Drop the attached agent mode files (`token-efficient.agent.md` and `flash-worker.agent.md`) into your VS Code prompts folder:

- **Windows (remote-ssh workflow):** `%APPDATA%\Code\User\prompts\` in File Explorer on your laptop
- Use `Code - Insiders` instead of `Code` for the Insiders build

This pairs GPT-5.4 as the "brain" (planning, decisions) with **Gemini 3 Flash** as a cheap delegation "worker" (file reads, command execution, exploration, and other token-heavy grunt work). In my experiment, this offloaded **80% of LLM calls** to Flash and cut costs by an additional **35%** on top of the model switch.

The agent mode also bakes in several prompt-level optimizations:

- **Tool call batching** — batch independent tool calls into single turns, reducing expensive brain LLM requests
- **File intermediates** — redirect large command output to temp files and sample it, keeping context lean instead of dumping 20K+ tokens into the window
- **Aggressive delegation boundaries** — clear rules for what stays in the brain vs. what gets handed off to Flash

Bonus: delegation doesn't just save money — it keeps the brain's context smaller and cleaner, which leads to *better* decisions and fewer hallucinations.

**Why a custom agent mode instead of instructions or skills?**

I tried all three. Here's why I landed on agent modes:

- **Skills** are dynamically discovered and loaded — the agent chooses *when* to apply them. That's the wrong shape for optimizations like these. When you want token efficiency, you want it all the time, not when the agent feels like it.
- **Always-on instructions**  seemed like the ideal fit — layer optimizations on top of the built-in agent modes. But in practice, adherence was poor. The instructions seemed to conflict with the agent mode's own prompts, and the agent would routinely ignore delegation rules and batching directives.
- **Custom agent modes** gave dramatically better results. The agent follows its own mode's instructions much more reliably than layered-on repo instructions, and the combined effect (delegation + batching + file intermediates + output discipline) is greater than the sum of the parts.

The tradeoff is that you lose the built-in agent mode's features when using a custom one. In practice, the savings more than compensate, and we can work on closing the gaps.

---


## 🔧 VS Code Optimization Settings (Bonus — 2 min)

These aren't in the core quick start because they're largely preview features, and many don't work yet (although this might be because of our org settings), but they're proof that Microsoft is working on including these features natively. When enabled, they will do everything the attached custom agents do, but better. Add to your `settings.json` (Ctrl+Shift+P → "Preferences: Open User Settings (JSON)"):

```json
{
    "chat.agent.maxRequests": 999,
    "chat.exploreAgent.defaultModel": "Gemini 3 Flash (Preview) (copilot)",
    "chat.planAgent.defaultModel": "GPT-5.4 (copilot)",
    "chat.tools.compressOutput.enabled": true,
    "chat.tools.confirmationCarousel.enabled": true,
    "github.copilot.chat.agent.currentEditorContext.enabled": false,
    "github.copilot.chat.agent.omitFileAttachmentContents": true,
    "github.copilot.chat.codesearch.enabled": true,
    "github.copilot.chat.executionSubagent.enabled": true,
    "github.copilot.chat.executionSubagent.model": "Gemini 3 Flash (Preview)",
    "github.copilot.chat.executionSubagent.toolCallLimit": 25,
    "github.copilot.chat.exploreAgent.model": "Gemini 3 Flash (Preview)",
    "github.copilot.chat.feedback.onChange": true,
    "github.copilot.chat.getChangedFilesTool.enabled": true,
    "github.copilot.chat.gpt55EconomicalSearchAndEdit.enabled": true,
    "github.copilot.chat.scopeSelection": true,
    "github.copilot.chat.searchSubagent.enabled": true,
    "github.copilot.chat.searchSubagent.model": "Gemini 3 Flash (Preview)",
    "github.copilot.chat.searchSubagent.thoroughnessEnabled": true,
    "github.copilot.chat.searchSubagent.toolCallLimit": 10,
    "github.copilot.chat.skillTool.enabled": true
}
```

**What these do:** Route iterative work (search, execution, exploration) to Flash instead of the expensive primary model, compress tool output before it enters context, prevent attached files from being dumped verbatim, and enable smarter search behavior. Everything the custom agents do, but applied globally.

---

## 📚 Additional Resources

**[RTK](https://github.com/rtk-ai/rtk) — CLI Output Compression.** Compresses CLI output before it enters the LLM context (claims 60-90% on shell commands). The catch: no first-class Copilot support, manual per-repo install, and mixed agent adherence to shell-preference rules. Worth knowing about, but Microsoft is adding very similar output-limiting features natively (already in Insiders preview), making this increasingly redundant.

**[Fabric](https://github.com/danielmiessler/fabric) — Prompt Template Library.** 200+ crowdsourced prompt templates with useful structural insights (identity, steps, output format, constraints). The principles are solid, but finding the right pattern, integrating it, and fine-tuning it per-task is more effort than the savings justify. Better to internalize the principles and apply them directly.

**[lmarena.ai](https://lmarena.ai)** — Crowdsourced subjective model rankings (formerly Chatbot Arena). Useful for comparing model capability.

**[artificialanalysis.ai](https://artificialanalysis.ai)** — Price-vs-performance benchmarks across models. Useful for making cost-informed model choices.
