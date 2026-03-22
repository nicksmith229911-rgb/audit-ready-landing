# Environment Variable Validation

The following table compares the current and proposed values for the required environment variables based on the `.env` file and the root directory contents:

| Variable | Current Value | Updated Value | Notes |
| :--- | :--- | :--- | :--- |
| `VERTEX_LOCATION` | *Missing* | `global` | Will be added to meet requirements. |
| `GEMINI_MODEL_ID` | *Missing* | `gemini-3-flash-preview` | Will be added for the specified Gemini model. |
| `CLAUDE_MODEL_ID` | *Missing* | `claude-opus-4-6@default` | Will be added for the specified Claude model. |
| `LLAMA_MODEL_ID` | *Missing* | `llama-4-maverick-17b-128e-instruct-maas` | Will be added for the specified Llama model. |
| `GOOGLE_APPLICATION_CREDENTIALS` | `service-account.json` | `service-account.json` | Validated. The `service-account.json` file exists in the root directory. |
