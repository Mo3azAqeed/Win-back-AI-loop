# Python for the learning engine, TypeScript for the app integration

The simulation and the learning engine (choosing variants, scoring outcomes, keeping lessons) are written in Python, because its statistics and simulation tooling is the strongest fit for that work. The parts that plug into our app later (Shopify and email-provider webhooks, sending, consent) are written in TypeScript, so they live next to the app. The first milestone is the simulation, so it is pure Python; how the two halves talk to each other is decided when the integration is built.
