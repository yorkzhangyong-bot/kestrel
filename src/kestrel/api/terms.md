version: 3

By ticking "I own this agent or have written permission to test it", you confirm that:

- you own this agent, or its owner has given you written permission to test it;
- you are responsible for every test and scan you run against it with Kestrel.

Kestrel only sends the agent plain conversational messages, within fixed limits on time, size and the number of messages. It never floods the agent with requests or tries to overload it.

When Kestrel judges whether an attack worked, it sends the attack message and the agent's reply to a third-party model provider to score them. Do not test an agent whose replies you may not share with that provider. Your stored auth header values are never sent there.

In an adaptive attack, a third-party attacker model also drives the conversation, so the agent's replies are sent to the attacker model's provider as well as the judge's. Do not run an adaptive attack against an agent whose replies you may not share with those providers.
