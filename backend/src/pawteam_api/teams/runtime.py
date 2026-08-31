"""Runtime-only Team capability description and delegation argument contract."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class DelegateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str = Field(min_length=1, max_length=36)
    target_agent_id: str = Field(min_length=1, max_length=36)
    task: str = Field(min_length=1, max_length=8_000)


@dataclass(frozen=True)
class DelegationMember:
    agent_id: str
    name: str
    description: str


@dataclass(frozen=True)
class DelegationTeam:
    team_id: str
    name: str
    members: tuple[DelegationMember, ...]


def delegation_tool_definition(
    teams: tuple[DelegationTeam, ...],
) -> dict[str, object]:
    roster = "; ".join(
        f"{team.name} ({team.team_id}): "
        + ", ".join(f"{member.name} ({member.agent_id})" for member in team.members)
        for team in teams
    )
    schema = DelegateArguments.model_json_schema()
    properties = schema.get("properties")
    if isinstance(properties, dict):
        team_property = properties.get("team_id")
        if isinstance(team_property, dict):
            team_property["enum"] = [team.team_id for team in teams]
        target_property = properties.get("target_agent_id")
        if isinstance(target_property, dict):
            target_property["enum"] = [
                member.agent_id for team in teams for member in team.members
            ]
    return {
        "type": "function",
        "function": {
            "name": "delegate_to_agent",
            "description": (
                "Delegate one bounded task to an allowed Team member and wait for "
                f"that Agent's result. Available roster: {roster}"
            ),
            "parameters": schema,
        },
    }


def team_prompt_section(teams: tuple[DelegationTeam, ...]) -> str:
    lines = [
        "你是协调 Agent，可以使用 delegate_to_agent 把边界清晰的任务交给成员。",
        "不要把整个用户请求原样转交；说明目标、输入、约束和期望输出。",
        "成员只读取自己的 Workspace、Skill 和 Tool 权限，不会继承你的权限。",
    ]
    for team in teams:
        lines.append(f"\nTeam: {team.name} ({team.team_id})")
        for member in team.members:
            lines.append(
                f"- {member.name} ({member.agent_id}): "
                f"{member.description or '未填写职责'}"
            )
    return "\n".join(lines)
