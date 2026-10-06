# LLM Usage & Code Generation Note

## 1. Development Tools & Model
- **AI Assistant:** Google Antigravity IDE (Gemini 3.8 Flash)
- **Application Model:** `openai/gpt-oss-120b` via Groq Cloud API with native Tool Calling (`lookup_catalog`).

## 2. AI Code Generation: Task, Bug Discovery, and Verification
During the implementation of the pricing module (`src/pricing.py`), the AI assistant initially generated the volume discount using standard Python floating-point math:

```python
# Initial AI-generated code:
discount = gross_cents * 0.10
total_cents = int(round(gross_cents - discount))
```

### Flaws Discovered during Inspection:
1. **Floating-Point Drift:** Binary floats produce rounding anomalies (e.g. `0.1 + 0.2 != 0.3`).
2. **Banker's Rounding:** Python's built-in `round()` rounds half-cents to the nearest *even* number (`2.5 -> 2`), directly violating Rule 2 of `tasks/orders/domain.md` (*"halves rounded up"*).

### Correction Applied:
I instructed the assistant to use exact `decimal.Decimal` arithmetic with `ROUND_HALF_UP`:

```python
gross_decimal = Decimal(str(gross_cents))
discount_rate = Decimal("0.10")
raw_discount = gross_decimal * discount_rate
discount_cents = int(raw_discount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

### Verification:
I added a dedicated unit test `test_round_half_up_rule` testing 15 units @ 135¢ grossing 2025¢, verifying that the 202.5¢ discount strictly rounds up to 203¢.
```

