# Release and Branch Playbook

This repository uses two long-lived branches:
- `master`: stable branch for release-ready code
- `develop`: integration branch for ongoing work

## Pull Request Rules

- PRs into `master` must come from one of:
  - `develop`
  - `hotfix-*`
  - `codex/hotfix-*`
- For urgent production fixes, use `hotfix-*` (or `codex/hotfix-*`) and merge to `master` first.
- After hotfix merge to `master`, sync `master` back into `develop`.

## Tag Rules

- Stable release tag (from `master`): `vX.Y.Z`
  - Example: `v2.2.0`
- Prerelease tag (from `develop`): `vX.Y.Z-bN`
  - Example: `v2.1.3-b1`

## Automated Release Workflow

Workflow file:
- `.github/workflows/create-release-from-tags.yml`

Behavior:
- On tag push `v*`, validate format and source branch.
- Build zip assets for:
  - `GIMP`
  - `Krita`
  - `coa_tools2`
  - `Photoshop`
  - `Godot`
- Create GitHub release draft:
  - `vX.Y.Z` => stable draft release
  - `vX.Y.Z-bN` => draft prerelease

## Manual Fallback (if automation fails)

1. Check workflow logs and fix root cause if needed.
2. If release is urgent, create release manually from the same tag.
3. Upload the same five zip assets listed above.
4. Keep title/notes consistent with tag type (stable vs prerelease).

## Branch Cleanup Policy

- Delete remote branches only when they are clearly merged into `master` or `develop`.
- Do not delete branches that still contain unique commits.
- Keep active work branches until the owner confirms cleanup.

## Codex Issue Fix Workflow

在此仓库中并行修复 GitHub issue 时，请遵循以下基本步骤。

- 首先查看 GitHub issues 和 Project `coa_tools2 tasks`，根据重要程度、冲突风险和验证难易度确定工作顺序。
- 每个 issue 分配 1 个 worktree / 1 个 branch。
- branch 通常以 `develop` 为起点，命名为 `codex/issue-<编号>-<简短说明>`。仅 release / hotfix 面向 `master`。
- 即使存在旧的 issue branch，也不要直接在其上作业，而是从当前的 `develop` 起点 branch 中仅参考所需差异。
- 使用 subagent 时，需明确指定负责的 worktree、目标 issue、可编辑范围、验证条件和提交方针。
- 务必告知 subagent「由于其他 agent 也在同时作业，请勿还原其他 worktree 或他人的更改」。
- 若当前 subagent tool 无法指定 `gpt-4.5`，则省略 model override，将 `reasoning_effort` 设为 `high` 或 `xhigh`。
- DCC 实机验证（Blender / Krita / GIMP）由 main agent 串行执行。涉及 GUI 或用户设置同时操作的验证，请勿让 subagent 并行执行。
- 除用户明确要求外，PR 不要设为 draft，应作为普通的 ready for review 创建。
- PR title / body 用英文撰写。内部备忘录或面向用户的报告可用中文。
- GitHub PR body 请使用 `--body-file`，并在 PowerShell 中避免 `\n` 被字面化。
- 完全修复的 issue 使用 `Fixes #...`，部分修复或相关确认使用 `Refs #...`。
- PR 创建后，将对应 issue 和 PR 的 Project Status 设为 `In review`。
- 若验证中需要操作 Krita / GIMP 的用户 plugin 文件夹，务必事先备份，验证后恢复原状。