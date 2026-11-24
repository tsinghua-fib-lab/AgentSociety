# dataset.json Schema

## Full Schema

```json
{
  "id": "lowercase-slug-with-dashes",
  "name": "Human-readable name",
  "description": "What this dataset contains",
  "category": "surveys",
  "version": "1.0.0",
  "tags": ["tag1", "tag2"],
  "author": "Author Name",
  "license": "CC BY 4.0"
}
```

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique slug identifier. Must match `^[a-z0-9_-]+$` |
| `name` | string | Yes | Human-readable display name |
| `description` | string | Yes | Summary of dataset contents |
| `category` | string | Yes | One of: `agent_profiles`, `surveys`, `experiments`, `literature`, `simulation_results`, `other` |
| `version` | string | Yes | Semantic version (e.g. `1.0.0`) |
| `tags` | string[] | No | Searchable tags |
| `author` | string | Yes | Author name or team |
| `license` | string | No | License identifier (e.g. `CC BY 4.0`) |

## Metadata Alignment

The `dataset.json` fields are sent directly to the backend API during `upload`. After downloading via `agentsociety-use-dataset`, the data is stored in a normalized `metadata.json` with additional fields (`source`, `installed_at`, `package_size_bytes`). The core fields (`id`, `name`, `version`, etc.) are shared between both formats.

## Defaults

| Setting | Value |
|---------|-------|
| Casdoor URL | `https://login.fiblab.net` |
| Backend URL | `https://agentsociety2.fiblab.net` |
| Client ID | `7ffcbfe4ae0fcb2c0d63` |
