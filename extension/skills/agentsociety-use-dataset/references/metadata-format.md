# Downloaded Metadata Format

Downloaded datasets store a normalized `metadata.json` aligned with the API schema:

```json
{
  "id": "dataset-slug",
  "name": "Display Name",
  "description": "...",
  "category": "surveys",
  "version": "1.0.0",
  "tags": ["tag1"],
  "author": "Author",
  "license": "CC BY 4.0",
  "source": "remote",
  "installed_at": "2026-04-09T12:00:00Z",
  "package_size_bytes": 1024,
  "created_at": "2026-04-08T10:00:00Z",
  "updated_at": "2026-04-09T08:00:00Z"
}
```

## Additional Fields (beyond dataset.json)

| Field | Description |
|-------|-------------|
| `source` | Always `"remote"` for downloaded datasets |
| `installed_at` | ISO 8601 timestamp of when the dataset was downloaded |
| `package_size_bytes` | Size of the original ZIP package |
| `created_at` | When the dataset was created on the platform |
| `updated_at` | When the dataset was last updated on the platform |

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--server` | string | `https://agentsociety2.fiblab.net` | Backend API URL |
| `--output` | string | `./datasets/` | Download output directory |
| `--datasets-dir` | string | `./datasets/` | Local datasets directory |
| `--category` | string | -- | Filter by category |
| `--tags` | string | -- | Comma-separated tag filter |
| `--limit` | int | 20 | Max search results |
| `--skip` | int | 0 | Pagination offset |
| `--all` | flag | false | Show merged local+remote view |
| `--remote` | flag | false | Show remote datasets only |

## Defaults

| Setting | Value |
|---------|-------|
| Backend URL | `https://agentsociety2.fiblab.net` |
| Local datasets dir | `./datasets/` |
