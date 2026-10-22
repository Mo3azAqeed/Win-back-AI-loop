# Win-back AI loop

An email loop that wins back merchants who stall in our store-cloning Shopify app: they sign up and do nothing (**Idle**), save a draft but never publish (**Drafter**), or publish but never pay (**Trialist**). An LLM writes email variants, a statistical scorer picks which one each merchant gets, and every outcome feeds back so the next choices get better.

**Milestone 1** is a simulation: made-up merchants, no real email. It answers whether the loop beats one good hand-written email at our real volume, and whether the lessons it learns are true.

- Spec: [#1](https://github.com/Mo3azAqeed/Win-back-AI-loop/issues/1), built in tickets #2–#14 and #16
- Glossary: [`CONTEXT.md`](CONTEXT.md) · Decisions: [`docs/adr/`](docs/adr) · Research: [`docs/research/win-back-ai-loop.md`](docs/research/win-back-ai-loop.md)
- Throwaway prototype: [`prototypes/win-back-sim.prototype.html`](prototypes/win-back-sim.prototype.html) (open it in a browser)

## How the code fits together

![How the code fits together](docs/diagrams/architecture.drawio.svg)

## What happens to one merchant

![What happens to one merchant in one segment](docs/diagrams/merchant-flow.drawio.svg)

## Build order

![Build order of tickets #2 to #14](docs/diagrams/build-order.drawio.svg)

The diagrams are `.drawio.svg` files: GitHub shows them as images, and you can open and edit them directly in [draw.io](https://app.diagrams.net).
