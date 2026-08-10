# Multi-language - `target_locales()`

Presents user activities in each user's preferred language at runtime. Applies to user
activity nodes.

## Flow methods

| Method                            | Notes                                                                              |
| --------------------------------- | ---------------------------------------------------------------------------------- |
| `aflow.target_locales([...])`     | Locales to translate into.                                                         |
| `aflow.source_locale("<code>")`   | Source language. Default `en`.                                                     |
| `aflow.translation_enabled(bool)` | Default `True`. `False` → `target_locales()` is ignored and no translations apply. |

```py
aflow.target_locales(["fr", "es", "de", "ja"])
aflow.source_locale("fr")
aflow.translation_enabled(True)
```

Call them inside the `@flow` builder function, alongside node definitions.

```py
@flow(name="multilingual_flow", description="A flow with multi-language support")
def build(aflow: Flow) -> Flow:
    user_flow = aflow.userflow()
    node = user_flow.field(direction="input", name="user_name",
                           display_name="Enter your name", kind=UserFieldKind.Text)
    user_flow.edge(START, node)
    user_flow.edge(node, END)

    aflow.target_locales(["fr", "es", "de", "ja"])

    aflow.sequence(START, user_flow, END)
    return aflow
```

## Round-trip

Configure locales → import the flow → export CSV → translate → import CSV.

### Export

```bash
orchestrate tools translation-export \
  -k flow \
  --name my_flow_name \
  --translation translations.csv
```

Or from a flow JSON file, before importing the flow:

```bash
orchestrate tools translation-export \
  -k flow \
  -f path/to/flowJson.json \
  --translation translations.csv
```

| Flag            | Type  | Req   | Notes                                               |
| --------------- | ----- | ----- | --------------------------------------------------- |
| `--kind` / `-k` | `str` | yes   | Must be `flow`.                                     |
| `--name` / `-n` | `str` | cond. | Imported flow tool name. Required unless `--file`.  |
| `--file` / `-f` | `str` | cond. | Path to a flow JSON file. Required unless `--name`. |
| `--translation` | `str` | yes   | Path for the CSV.                                   |

### CSV shape

| Column                | Contents                                        |
| --------------------- | ----------------------------------------------- |
| `key`                 | Unique identifier for the translatable element. |
| `en`                  | Source text (or your configured source locale). |
| `locale`              | Source locale code.                             |
| one per target locale | Your translations.                              |

```csv
key,en,locale,fr,es
form.instructions,Please fill out this form,en,Veuillez remplir ce formulaire,Por favor complete este formulario
form.submit_button,Submit,en,Soumettre,Enviar
field.name.label,Your Name,en,Votre nom,Su nombre
user_activity.user_name.display_name,Enter your name,en,Entrez votre nom,Ingrese su nombre
```

Key namespaces observed: `form.*`, `field.<name>.*`, `user_activity.<name>.*`.

The CSV must be **UTF-8** encoded or special characters break.

### Import

```bash
orchestrate tools translation-import \
  -k flow \
  --name my_flow_name \
  --translation translations.csv
```

Same flags as export.

## Runtime

The system presents each user activity in the user's preferred language automatically. No
per-node configuration is needed beyond `target_locales()`.
