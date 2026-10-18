# Advanced tracks — after v1.0

These are second-course material. Each is a 2–4 week extension on ATLAS. Pick by the job you're targeting.

## Track A — Fine-tuning and model serving (ML Engineer roles)
- **When**: stable style/format needs, domain vocabulary, cost at very high volume, latency floors.
- **Build**: distill the triage step into a small open model with PEFT/LoRA using Phase 7 datasets as training data and judges as the metric; serve with vLLM behind the ATLAS `provider=` switch; compare $/ticket, p95, and gate scores vs the API model.
- **Read**: Hugging Face PEFT docs; vLLM docs; DSPy "finetune bootstrap" (prompt-optimizer → distillation).

## Track B — Multimodal retrieval (document-heavy clients)
- **When**: runbooks are PDFs of screenshots, slide decks, scanned forms.
- **Build**: ColPali-style page-image embeddings for a subset of the corpus; late-chunking for text; a routed retriever (text vs visual); golden set with visual questions.
- **Read**: ColPali paper; late chunking; visual late chunking (ColChunk).

## Track C — Agent interoperability (platform roles)
- **When**: another organization's agent is the counterparty.
- **Build**: publish an ATLAS A2A Agent Card; accept tasks from a second agent; delegate a sub-task to an external agent; audit both directions.
- **Read**: A2A spec and SDK; AAIF project pages (MCP + A2A under one roof).

## Track D — Voice and real-time agents (contact-center clients)
- **When**: tickets arrive by phone.
- **Build**: STT → ATLAS FAQ route → TTS with barge-in; latency budget per hop; the same guardrails on transcripts.
- **Read**: provider realtime APIs; your own voice-pipeline notes.

## Track E — Deep Agents and long-running work
- **When**: multi-hour tasks (migrations, audits) rather than tickets.
- **Build**: rebuild one ATLAS route on the Deep Agents harness (planning tool, sub-agents, file-system memory); compare control, cost, observability.
- **Read**: LangChain Academy Deep Agents; Anthropic harness post.
