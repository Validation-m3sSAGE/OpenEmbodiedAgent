# Target Resolution

## 1. Choose the Plugin Checkout to Edit

Prefer these locations in order:

1. Sibling source repo: `../PhyAgentOS-rekep-real-plugin`
2. Installed plugin checkout: `~/.PhyAgentOS/plugins/repos/rekep_real`

If neither exists, stop and tell the user to clone or deploy the plugin first.

## 2. Default SDK Placement

The preferred SDK drop directory is:

```text
<plugin_repo>/runtime/third_party/<robot_slug>/
```

Examples:

- `../PhyAgentOS-rekep-real-plugin/runtime/third_party/mycobot_sdk/`
- `~/.PhyAgentOS/plugins/repos/rekep_real/runtime/third_party/fr3_sdk/`

If the user already placed the SDK elsewhere inside the plugin repo, work with that path directly. Only ask a follow-up question when the SDK location is ambiguous.

## 3. Inspect Before You Design

Read the smallest useful set of files first:

- top-level `README*`
- `requirements*.txt`, `pyproject.toml`, `setup.py`
- example scripts
- connection/session classes
- motion, gripper, and state APIs

Do not guess the API surface if the SDK can be inspected locally.
