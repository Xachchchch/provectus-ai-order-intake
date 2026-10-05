# AI workflow used during this exercise

Complete this file and rename it to README.md. Copy the manifest template to manifest.json. Keep only entries relevant to the exercise, while explicitly marking unused categories as `not-used`.

## Tools and models

Record coding tools, plugins, extensions and their versions, providers, model IDs, and settings you changed. Distinguish development-time tools from the model integration inside your application. Include model parameters such as temperature or output limits when you set them. Record defaults when no setting was changed; mark unavailable details as not-exportable and explain them.

## Configuration files

List the original repository path or sanitized snapshot path for every skill, agent instruction, subagent definition, hook, prompt, rule file, tool/MCP configuration, and permission setting that affected this exercise. Include referenced hook scripts. Save all project configuration at its normal location or under this folder and explain how to restore it. Preserve relevant versions used earlier in the exercise through Git history or named snapshots.

For user-level configuration, include only the applicable sections in sanitized copies. Never copy a whole personal configuration directory. Record each redaction or omitted setting and its purpose without its value. Use an .env.example for variable names; exclude API keys, tokens, credentials, private URLs, and unrelated personal information.

## One workflow example

Describe one instruction you gave, which configuration affected it, how you checked the result, and one correction or improvement. Include a small relevant prompt excerpt or saved result. Full chat logs are not required.

## Reproduce or replay

Explain where configuration belongs, the command to run, required tools and versions, and how to replay saved real responses without credentials. Describe what a hook does and when it runs; do not rely on a reviewer enabling it without reading it.

## Decisions and limitations

Explain why the setup suited the task and what you would change. A default setup is acceptable. Do not create unused skills, agents, or hooks to fill the manifest. Record `not-used`, `default`, `used`, `redacted`, or `not-exportable` accurately.
