---
name: generate-assignment-data
description: Extend the fictional starter data for one Junior AI Engineer take-home task using its supplied domain rules and templates. Use during fixture preparation, not to implement or grade the candidate application.
---

# Generate assignment data

Read the selected task's `domain.md`, seed files, and expected seed results or reference cases in `../../tasks/<task>/`. If the task is not identified, ask which of the seven folders to use. Work only on that task's fixtures.

Treat the exercise rules as fixed. Do not add real-world accounting, legal, logistics, pricing, or compliance rules. Preserve seed IDs and relationships. State unresolved ambiguity instead of silently inventing a policy.

Use the assignment's suggested size as a guide. Generate only enough additional examples to cover its listed checks within 30–60 minutes. Follow the provided template fields. For invoices, reuse the two layouts. For code tasks, preserve the supplied baseline and reference checks. For UI work, use the supplied portal.

Save fictional inputs as a fixed snapshot and describe the generation method. Include a seed if random generation is used. Keep expected results in a separate file, with each result linked to its input and the rule that determines it. When rows change an aggregate, recompute its expectation; seed totals apply only to seed rows.

Check arithmetic with code, relationships by ID, and document answers against the cited passage. Flag deliberate invalid cases separately from accidental data errors. Ask the candidate to inspect five reference cases and verify expected results independently of the application being assessed. Do not accept the application's output as the answer key.

Finish with the generated file list, cases covered, and unresolved questions. Do not claim the fixtures establish real-world model accuracy. Do not create application code, run live integrations, or modify the candidate's global AI settings as part of data generation.
