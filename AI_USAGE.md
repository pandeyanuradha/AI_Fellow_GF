# AI usage

Disclosure of how AI tooling was used during the work.

I used GitHub Copilot agent's help throughout. The agent mainly worked on writing comments, drafting `.md` files, and helping me debug. Some specific points where it came in really handy:

- **Implementation of the evaluator.** The assistant wrote most of the report template, FastAPI endpoint, RAG pipeline, Dockerfile, and provider-configurable LLM client.

- **Live validation.** I installed CeRAI's full 9-service stack and ran it end-to-end (the agent helped work around the Apple-Silicon Selenium blocker).

- **Voice dataset.** The assistant helped me build the dataset for the voice evaluation (Hindi & English). 
