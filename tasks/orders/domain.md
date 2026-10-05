# Order intake: exercise rules

These fictional rules are the source of truth for this assignment. No industry research is required.

1. All prices are fictional USD amounts stored in integer cents. Quantities are positive whole numbers of individual items. Do not infer how many items a box contains.
2. Use the catalog unit price. For a line with at least 10 items, apply a 10% discount to that line only; round the discount to the nearest cent, with halves rounded up. There are no other charges.
3. Match products by SKU or an unambiguous catalog description. Unknown products and ambiguous quantities need clarification.
4. Requests with the same order reference describe the same order. Reprocessing an identical request must not create a second draft.

## Worked example

Two CAB-1 cables at 2,000 cents each total 4,000 cents. Ten CAB-1 cables total 18,000 cents after the 2,000-cent bulk discount.

## Extend the starter

Keep the supplied catalog and pricing rules. Add wording variations and enough requests to cover the brief, including a reviewer correction. Check the totals by hand or separate arithmetic code.

Record any unresolved ambiguity in your README. Do not silently add domain rules. Keep seed cases and their expected results so the reviewer can run the same checks.
