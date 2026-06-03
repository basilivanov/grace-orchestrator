## TZ Compliance Rule
When given a TZ/спецификацию:
- Use EXACT field names from the TZ, not existing codebase names
- Use EXACT function signatures from the TZ
- If TZ conflicts with existing code → change the code, not the TZ
- Check every TZ requirement against implementation before declaring "done"
- Do NOT substitute "it works" for "it matches the spec"

## Coder mode
- You are not the architect.
- Do not rename spec fields.
- Do not replace required functions/classes with convenient equivalents.
- If implementation conflicts with TZ, change implementation.
- If exact implementation is impossible, stop and return BLOCKER.
