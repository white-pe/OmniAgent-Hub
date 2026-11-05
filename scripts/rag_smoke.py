"""手动联调已有 RAG 资源，不创建 Provider、知识库或测试数据。

从项目根目录运行 ``uv run python scripts/rag_smoke.py --help`` 查看参数。
默认执行真实向量化和索引；--check-only 只检查现有业务资源及索引状态。
启用平台认证时，两种模式都会先调用登录接口。
模型密钥由后端读取，本脚本只在需要登录时交互输入平台管理员密码。
"""

import argparse
import json
from getpass import getpass
from uuid import UUID

import httpx


class SmokeError(RuntimeError):
    """联调失败，携带当前步骤的说明。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    # 提前校验 UUID，避免拼错资源 ID 后仍然发送请求。
    for name in ("document", "version", "chunk-set", "profile"):
        parser.add_argument(f"--{name}-id", type=UUID, required=True)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只检查现有业务状态，不向量化、不执行索引",
    )
    parser.add_argument(
        "--verify-reuse",
        action="store_true",
        help="执行后重复调用一次，检查两项操作均复用已有结果",
    )
    parser.add_argument(
        "--qdrant-url",
        help="可选：直接核对指定 Qdrant 中当前批次的实际点数",
    )
    args = parser.parse_args()
    if args.check_only and args.verify_reuse:
        parser.error("--check-only 与 --verify-reuse 不能同时使用")
    return args


def call(client: httpx.Client, method: str, path: str, **kwargs):
    """统一输出步骤并转换失败响应，第一处失败后立即停止。"""

    print(f"\n{method} {path}", flush=True)
    response = client.request(method, path, **kwargs)
    if not response.is_success:
        try:
            detail = response.json().get("detail", "请求失败")
        except (ValueError, AttributeError):
            # 网关可能返回 HTML，不直接打印原始页面及内部信息。
            detail = "服务返回非标准错误响应，请检查服务端日志"
        raise SmokeError(f"HTTP {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as error:
        raise SmokeError("接口成功响应不是有效 JSON") from error


def login(client: httpx.Client) -> None:
    status = call(client, "GET", "/api/auth/status")
    if not status["auth_enabled"]:
        return
    call(
        client,
        "POST",
        "/api/auth/login",
        json={"password": getpass("平台管理员密码：")},
    )
    token = client.cookies.get("pawteam_csrf")
    if not token:
        raise SmokeError("登录后缺少 CSRF Cookie，请检查地址和部署配置")
    client.headers["x-csrf-token"] = token


def verify_state(state, expected: int) -> None:
    """数据库中的完成状态和点数必须同时正确。"""

    if state is None or state.get("status") != "indexed":
        raise SmokeError(f"索引尚未完成：{json.dumps(state, ensure_ascii=False)}")
    if (
        state["expected_points"] != expected
        or state["indexed_points"] != expected
    ):
        raise SmokeError(f"索引点数与当前批次的 {expected} 个片段不一致")


def verify_qdrant(url: str, profile_id: UUID, chunk_set_id: UUID, expected: int):
    """按批次过滤后精确计数，不能拿整个集合的点数与单批次比较。"""

    collection = f"omniagent_embedding_{profile_id.hex}"
    # 使用独立客户端，不把平台的登录 Cookie 发给 Qdrant。
    with httpx.Client(base_url=url, timeout=15.0) as client:
        result = call(
            client,
            "POST",
            f"/collections/{collection}/points/count",
            json={
                "exact": True,
                "filter": {
                    "must": [
                        {"key": "profile_id", "match": {"value": str(profile_id)}},
                        {"key": "chunk_set_id", "match": {"value": str(chunk_set_id)}},
                    ]
                },
            },
        )
    count = result["result"]["count"]
    if count != expected:
        raise SmokeError(f"Qdrant 实际点数为 {count}，预期为 {expected}")
    print(f"Qdrant 当前批次实际点数：{count}")


def run(args: argparse.Namespace) -> None:
    chunk_path = (
        f"/api/knowledge-documents/{args.document_id}"
        f"/versions/{args.version_id}/chunk-sets/{args.chunk_set_id}"
    )
    embedding_path = f"{chunk_path}/embeddings/{args.profile_id}"
    index_path = f"{chunk_path}/indexes/{args.profile_id}"

    # 这里的超时针对网络操作，不是整个模型批次的绝对执行期限。
    # with 保证成功、异常退出时都能关闭 HTTP 连接。
    with httpx.Client(base_url=args.base_url, timeout=180.0) as client:
        login(client)
        profile = call(
            client, "GET", f"/api/knowledge-embedding-profiles/{args.profile_id}"
        )
        print(f"模型：{profile['model_name']}，维度：{profile['dimensions']}")
        # 只获取一条正文以控制响应大小，total 是整个批次的片段数。
        page = call(client, "GET", f"{chunk_path}/chunks", params={"limit": 1})
        expected = page["total"]
        if expected < 1:
            raise SmokeError("切块批次为空，请先检查解析和切块结果")
        print(f"片段数：{expected}")

        if not args.check_only:
            print("开始真实向量化；未生成的向量可能产生模型调用费用。")
            embedded = call(client, "POST", embedding_path)
            if embedded["chunk_count"] != expected:
                raise SmokeError("向量化返回的片段数与批次不一致")
            print(json.dumps(embedded, ensure_ascii=False, indent=2))
            indexed = call(client, "POST", index_path)
            if indexed["point_count"] != expected:
                raise SmokeError("索引返回的点数与批次不一致")
            print(json.dumps(indexed, ensure_ascii=False, indent=2))

        state = call(client, "GET", index_path)
        verify_state(state, expected)
        if args.verify_reuse:
            # 先后两次执行，而非并发。并发请求可能重复调用付费模型。
            for path in (embedding_path, index_path):
                reused = call(client, "POST", path)
                if reused["reused"] is not True:
                    raise SmokeError(f"操作未按预期复用已有结果：{path}")
            print("向量化与索引的重复调用均复用成功")

    if args.qdrant_url:
        verify_qdrant(
            args.qdrant_url, args.profile_id, args.chunk_set_id, expected
        )
    print(f"\n联调通过：{expected} 个片段，索引状态 indexed。")
    if not args.qdrant_url:
        print("本次未直接检查 Qdrant；需要时传入 --qdrant-url。")


if __name__ == "__main__":
    arguments = parse_args()
    try:
        run(arguments)
    except httpx.TimeoutException:
        # HTTP 客户端超时不能证明服务端已停止；先查状态再决定重试。
        print("\n联调失败：请求超时。请先查看后端日志和索引状态。")
        raise SystemExit(1) from None
    except httpx.RequestError:
        print("\n联调失败：无法完成网络请求，请检查地址、服务和代理配置。")
        raise SystemExit(1) from None
    except SmokeError as error:
        print(f"\n联调失败：{error}")
        raise SystemExit(1) from None
