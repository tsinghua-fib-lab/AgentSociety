# Profile Design

Profiles are flexible dictionaries - no schema enforced.

## Standard Fields

```json
{
  "id": 1,
  "name": "Alice",
  "age": 30,
  "gender": "Female",
  "education": "Bachelor's degree",
  "occupation": "Engineer",
  "consumption": "medium"
}
```

## Custom Fields by Agent Type

**Student**: `grade`, `major`, `learning_style`, `study_hours`

**Consumer**: `income_level`, `spending_habits`, `brand_preferences`

**Worker**: `occupation`, `work_hours_per_week`, `job_satisfaction`

**Game**: `strategy`, `risk_tolerance`, `trust_level`

## Accessing Profile

```python
profile = self.get_profile()
name = profile.get("name", "Unknown")
age = profile.get("age", 0)

# In prompts
prompt = f"You are {profile.get('name')}, age {profile.get('age')}."
```

## Best Practices

- Keep values JSON-serializable
- Use sensible defaults with `.get(key, default)`
- Document expected fields in `init_description()` and keep `description()` short
- Don't store sensitive data
