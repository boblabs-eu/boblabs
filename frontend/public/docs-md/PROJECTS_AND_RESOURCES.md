# Bob Labs — Projects & Resources

## Overview

Projects and Resources are organizational entities in Bob Labs for managing work items, documentation links, and knowledge. Both support ACL-based access control, theming, and cross-linking.

## Concepts

| Concept | Description |
|---------|-------------|
| **Project** | A work item with metadata, links, notes, commands, and theme tags |
| **Resource** | A reusable knowledge item (doc, tool, reference) linkable to projects |
| **Theme** | A color-coded tag for categorizing projects and resources |
| **Link** | Project/resource can carry multiple URL references |

## Data Model

### Project

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `name` | string | Project name |
| `description` | string | Project description |
| `github_url` | string | Repository URL |
| `links` | string[] | Additional URLs |
| `themes` | string[] | Theme tags |
| `notes` | string[] | Free-form notes |
| `useful_commands` | string[] | Shell commands for quick reference |
| `acl` | object | Access control list |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last modification |

### Resource

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `name` | string | Resource name |
| `description` | string | Resource description |
| `links` | string[] | URLs |
| `themes` | string[] | Theme tags |
| `notes` | string[] | Free-form notes |
| `acl` | object | Access control list |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last modification |
| `projects` | Project[] | Linked projects (detail view only) |

## API Endpoints

### Projects — `/api/v1/projects`

All project endpoints require authentication.

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/projects` | — | List all accessible projects |
| POST | `/projects` | — | Create a project |
| GET | `/projects/{project_id}` | VIEW | Get project details |
| PUT | `/projects/{project_id}` | EDIT | Update project fields |
| DELETE | `/projects/{project_id}` | DELETE | Delete a project |
| GET | `/projects/{project_id}/resources` | — | List linked resources |

### Resources — `/api/v1/resources`

All resource endpoints require authentication.

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/resources` | — | List all accessible resources |
| POST | `/resources` | — | Create a resource |
| GET | `/resources/{resource_id}` | VIEW | Get resource with linked projects |
| PUT | `/resources/{resource_id}` | EDIT | Update resource fields |
| DELETE | `/resources/{resource_id}` | DELETE | Delete a resource |
| GET | `/resources/{resource_id}/projects` | — | List linked projects |
| POST | `/resources/{resource_id}/projects` | — | Link to a project (409 if exists) |
| DELETE | `/resources/{resource_id}/projects/{project_id}` | — | Unlink from a project |

### Themes — `/api/v1/projects/themes`

Theme endpoints do not require specific permissions.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/projects/themes` | List all themes with colors |
| POST | `/projects/themes/rename` | Rename a theme across all projects |
| PUT | `/projects/themes/{theme_name}/color` | Set theme color |

## Resource–Project Linking

Resources and projects have a many-to-many relationship. A resource can be linked to multiple projects and vice versa.

```
Project A ──┐
            ├── Resource X
Project B ──┘

Project A ──── Resource Y
```

**Link a resource:**
```bash
curl -X POST http://localhost:8888/api/v1/resources/{resource_id}/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "uuid-here"}'
```

**Unlink:**
```bash
curl -X DELETE http://localhost:8888/api/v1/resources/{resource_id}/projects/{project_id} \
  -H "Authorization: Bearer $TOKEN"
```

## Access Control

Both projects and resources use the standard ACL system:

| Operation | Required Permission |
|-----------|-------------------|
| View | `VIEW` |
| Update | `EDIT` |
| Delete | `DELETE` |

The creator is automatically granted full permissions.

See [ACCESS_CONTROL.md](ACCESS_CONTROL.md) for details.

## Related Documents

- [ACCESS_CONTROL.md](ACCESS_CONTROL.md) — Permission system
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture
