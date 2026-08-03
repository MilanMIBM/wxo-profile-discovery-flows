# User assignment — `assign_to()`

Routes a user activity node to specific tenant users. Called on a `UserFlow`.

```py
from ibm_watsonx_orchestrate.flow_builder.flows.flow import UserFlow
from ibm_watsonx_orchestrate.flow_builder.types import UserAssignmentPolicy

user_flow: UserFlow = aflow.userflow()
user_flow.assign_to(policy=UserAssignmentPolicy.USER, assignees='flow.private.designated')
```

## Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `policy` | `UserAssignmentPolicy` | yes | Who receives the activity. |
| `assignees` | `str` | cond. | Expression resolving to user(s). Required when `policy=USER`. |

## `UserAssignmentPolicy`

| Value | Behavior |
| --- | --- |
| `FLOW_INITIATOR` | Assigns to whoever started the flow. This is the default when no policy is set, and always the behavior in Preview mode. |
| `USER` | Assigns to the user(s) resolved from `assignees`. |

## `assignees` expression forms

| Form | Example |
| --- | --- |
| JSON array with a user ID string | `'["123002B12G"]'` |
| Flow variable path referencing a user | `'flow.private.employee.manager'` |

The expression is evaluated at runtime and the activity is assigned to the resolved user.
A variable used this way must be of type `WXOUser`.

## Resolving a user by email

`WXOUser` values are obtained in a script node via the `system.user` helper, then stored in
private state.

```py
from ibm_watsonx_orchestrate_core.types.tools.types import WXOUser

class PrivateData(BaseModel):
    designated: WXOUser = Field(description="The user that will run the user flow")

@flow(name="...", private_schema=PrivateData)
def build(aflow: Flow) -> Flow:
    init = aflow.script(
        name="init_data",
        script="""flow.private.designated = system.user.search_by_email('user@example.com')[0]""",
    )

    user_flow: UserFlow = aflow.userflow()
    user_flow.assign_to(policy=UserAssignmentPolicy.USER, assignees='flow.private.designated')
    ...
    aflow.edge(START, init)
    aflow.edge(init, user_flow)
```

`search_by_email` returns a list; index it. The script node resolving the user must run
**before** the user flow it feeds.

## Multiple assignments in one flow

Each `userflow()` carries its own policy — mix assigned and initiator-facing activities
freely.

```py
designated_flow: UserFlow = aflow.userflow()
designated_flow.assign_to(policy=UserAssignmentPolicy.USER, assignees='flow.private.designated')

initiator_flow: UserFlow = aflow.userflow()
initiator_flow.assign_to(policy=UserAssignmentPolicy.FLOW_INITIATOR)
```

Cross-reference a value captured by one user flow from another by display name:

```py
text="Welcome {flow.userflow_1[\"Last name\"].output.value}"
```
