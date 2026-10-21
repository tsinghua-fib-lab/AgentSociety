import asyncio
import json
import random
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from agentsociety2.env import EnvBase, tool
from agentsociety2.env.base import load_int_map
from agentsociety2.logger import get_logger
from agentsociety2.storage import ColumnDef, ReplayDatasetSpec, TableSchema
from agentsociety2.storage.workspace_state import atomic_write_text

from .models import (
    Comment,
    CommentOnPostResponse,
    CreatePostResponse,
    FollowUserResponse,
    LikePostResponse,
    ObserveUserResponse,
    Post,
    RefreshFeedResponse,
    RepostResponse,
    SearchPostsResponse,
    SocialMediaPerson,
    UnfollowUserResponse,
    UnlikePostResponse,
    ViewPostResponse,
)
from .recommend import RecommendationEngine

_SOCIAL_MEDIA_EVENT_SCHEMA = TableSchema(
    name="social_media_event",
    columns=[
        ColumnDef(
            "id",
            "INTEGER",
            nullable=False,
            logical_type="identifier",
            analysis_role="identifier",
            description="Stable replay event identifier.",
        ),
        ColumnDef(
            "step",
            "INTEGER",
            nullable=False,
            logical_type="step",
            analysis_role="timestamp",
            description="Simulation step at which the social event was recorded.",
        ),
        ColumnDef(
            "t",
            "TIMESTAMP",
            nullable=False,
            logical_type="timestamp",
            analysis_role="timestamp",
            description="Simulation timestamp at which the social event was recorded.",
        ),
        ColumnDef(
            "sender_id",
            "INTEGER",
            nullable=False,
            logical_type="identifier",
            analysis_role="dimension",
            description="User ID of the event initiator.",
        ),
        ColumnDef(
            "action",
            "TEXT",
            nullable=False,
            logical_type="category",
            analysis_role="dimension",
            description="Social action type such as post, follow, like, comment, or repost.",
        ),
        ColumnDef(
            "content",
            "TEXT",
            logical_type="text",
            analysis_role="metadata",
            description="Human-readable content associated with the social event.",
        ),
        ColumnDef(
            "receiver_id",
            "INTEGER",
            logical_type="identifier",
            analysis_role="dimension",
            description="Optional user ID of the direct receiver for targeted actions.",
        ),
        ColumnDef(
            "target_id",
            "INTEGER",
            logical_type="identifier",
            analysis_role="dimension",
            description="Optional target object ID referenced by the action.",
        ),
    ],
    primary_key=["id"],
    indexes=[["step"], ["sender_id"], ["action"]],
)


_STATE_REL = "state/ENV_STATE.json"


class SocialMediaSpace(EnvBase):
    """
    Social Media Environment Module (e.g. Weibo/Twitter style).

    Agent 与社交媒体用户的对应关系：
    - 默认（未传 agent_id_name_pairs）：约定 agent_id === person_id。observe_user(person_id) 及
      各 tool 的 user_id 即仿真中的 agent id；用户来自 persons.json 或按需自动创建（_ensure_person_exists）。
    - 若传入 agent_id_name_pairs：显式列出参与本环境的 (agent_id, name)。
      此时仅允许这些 id 作为 user_id 使用；init() 时会为列表中尚未在 persons 数据里的 id 创建对应用户（username=name）。
    """

    # 声明式 per-person per-step 快照
    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef(
            "followers_count",
            "INTEGER",
            logical_type="count",
            analysis_role="measure",
            description="Number of followers owned by the user at this step.",
        ),
        ColumnDef(
            "following_count",
            "INTEGER",
            logical_type="count",
            analysis_role="measure",
            description="Number of accounts followed by the user at this step.",
        ),
        ColumnDef(
            "posts_count",
            "INTEGER",
            logical_type="count",
            analysis_role="measure",
            description="Number of posts created by the user at this step.",
        ),
    ]

    # ---- Skill Discovery ----

    @classmethod
    def skill_dirs(cls) -> list[Path]:
        """Return directories containing agent skills provided by SocialMediaSpace.

        Scans ``<module_dir>/agent_skills/`` for skill subdirectories each holding
        a ``SKILL.md`` (e.g. ``agent_skills/social-media/SKILL.md``). The env
        router picks these up and exposes them in the agent skill catalog so that
        agents learn how to interact with this social media environment.
        """
        skills_dir = Path(__file__).parent / "agent_skills"
        return [skills_dir] if skills_dir.is_dir() else []

    def __init__(
        self,
        persons: dict[int, Any] | None = None,
        posts: dict[int, Any] | None = None,
        comments: dict[int, list[Any]] | None = None,
        follows: dict[int, list[int]] | None = None,
        likes: dict[int, list[int]] | None = None,
        agent_id_name_pairs: list[tuple[int, str]]
        | list[list[int | str]]
        | None = None,
        **kwargs: Any,
    ):
        """
        初始化社交媒体空间环境。

        :param persons: 初始用户，key=person_id, value=SocialMediaPerson 可序列化 dict。
        :param posts: 初始帖子，key=post_id, value=Post 可序列化 dict。
        :param comments: 初始评论，key=post_id, value=该帖下的 Comment dict 列表。
        :param follows: 关注关系，key=person_id, value=被关注者 person_id 列表。
        :param likes: 点赞关系，key=person_id, value=被点赞的 post_id 列表。
        :param agent_id_name_pairs: 可选。显式 agent–用户映射 [(agent_id, name), ...]。
            **kwargs: feed_source, polarization_mode 等实验参数。
        """
        super().__init__()
        self._initial_persons = persons
        self._initial_posts = posts
        self._initial_comments = comments
        self._initial_follows = follows
        self._initial_likes = likes

        # 极化实验参数（feed 候选池与同阵营/异阵营比例）
        self._feed_source: str = str(kwargs.get("feed_source", "global"))
        self._polarization_mode: str = str(kwargs.get("polarization_mode", "none"))
        self._within_community_ratio: float = float(
            kwargs.get("within_community_ratio", 0.5)
        )
        self._community_detection: str = str(
            kwargs.get("community_detection", "follow_components")
        )
        _seed = kwargs.get("random_seed")
        self._random_seed: int | None = int(_seed) if _seed is not None else None

        # 并发锁，保护状态修改操作
        self._lock = asyncio.Lock()

        self._persons: dict[int, SocialMediaPerson] = {}
        self._posts: dict[int, Post] = {}
        self._comments: dict[int, list[Comment]] = defaultdict(list)

        self._next_post_id: int = 1
        self._next_comment_id: int = 1

        # 贴文推荐引擎（Feed Recommendation）；可选预训练模型路径与算法名
        self._rec_engine = RecommendationEngine(
            model_path=kwargs.get("recommendation_model_path"),
            recommendation_algorithm=kwargs.get("recommendation_algorithm", "mf"),
        )

        # 事件缓冲：tool 调用时追加，step() 末尾批量刷写到 replay DB
        self._pending_events: list[dict] = []
        self._event_id: int = 0
        self._recent_events = deque(maxlen=200)

        # Step counter for replay
        self._step_counter: int = 0

        # 显式 agent–用户映射：仅允许这些 id 作为 user_id
        self._allowed_user_ids: set[int] | None = None
        self._agent_names: dict[int, str] = {}
        if agent_id_name_pairs:
            pairs: list[tuple[int, str]] = []
            for pair in agent_id_name_pairs:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    pairs.append((int(pair[0]), str(pair[1])))
                else:
                    raise ValueError(
                        f"Invalid agent_id_name_pair: {pair}. Expected (int, str) or [int, str]"
                    )
            self._allowed_user_ids = {aid for aid, _ in pairs}
            self._agent_names = {aid: name for aid, name in pairs}

        get_logger().info("SocialMediaSpace initialized (in-memory data only)")

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json``（原子写）。

        持久化社交图（persons/posts/comments）+ 计数器 + 事件缓冲。
        ``_rec_engine``（预训练推荐器）不入盘——由 ``__init__`` 据
        ``recommendation_model_path``/``recommendation_algorithm``（在 env_kwargs）重建。
        ``_allowed_user_ids``/``_agent_names`` 由 agent_id_name_pairs 配置派生，不存。
        """
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "persons": {
                        str(pid): p.model_dump(mode="json")
                        for pid, p in self._persons.items()
                    },
                    "posts": {
                        str(pid): p.model_dump(mode="json")
                        for pid, p in self._posts.items()
                    },
                    "comments": {
                        str(pid): [c.model_dump(mode="json") for c in cs]
                        for pid, cs in self._comments.items()
                    },
                    "next_post_id": self._next_post_id,
                    "next_comment_id": self._next_comment_id,
                    "event_id": self._event_id,
                    "pending_events": list(self._pending_events),
                    "recent_events": list(self._recent_events),
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复社交图与缓冲。

        ``_rec_engine``/``_allowed_user_ids``/``_agent_names``/极化参数由
        ``__init__`` 从 kwargs 重建，不在此覆盖。``_comments`` 还原为
        ``defaultdict(list)``，``_recent_events`` 还原为 ``deque(maxlen=200)``。
        """
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        d = json.loads(state_path.read_text(encoding="utf-8"))
        self._persons = {
            pid: SocialMediaPerson.model_validate(p)
            for pid, p in load_int_map(d.get("persons")).items()
        }
        self._posts = {
            pid: Post.model_validate(p)
            for pid, p in load_int_map(d.get("posts")).items()
        }
        comments_raw = load_int_map(d.get("comments"))
        self._comments = defaultdict(
            list,
            {
                pid: [Comment.model_validate(c) for c in cs]
                for pid, cs in comments_raw.items()
            },
        )
        self._next_post_id = int(d.get("next_post_id", 1))
        self._next_comment_id = int(d.get("next_comment_id", 1))
        self._event_id = int(d.get("event_id", 0))
        self._pending_events = list(d.get("pending_events", []))
        self._recent_events = deque(d.get("recent_events", []), maxlen=200)
        self._step_counter = int(d.get("step_counter", 0))
        return True

    def _get_community_labels(self) -> dict[int, int]:
        """
        为每个用户分配社区标签 0 或 1，用于极化实验。
        """
        user_ids = set(self._persons.keys())
        if not user_ids:
            return {}
        # 若所有用户都有 camp_score，则直接用阵营分数
        if all(
            getattr(self._persons.get(uid), "camp_score", None) is not None
            for uid in user_ids
        ):
            labels: dict[int, int] = {}
            for uid in user_ids:
                s = getattr(self._persons[uid], "camp_score", None)
                labels[uid] = 0 if s is not None and s < 0.5 else 1
            return labels
        # 回退：parity 或 follow_components
        if self._community_detection == "parity":
            return {uid: int(uid % 2) for uid in user_ids}
        adj: dict[int, list[int]] = defaultdict(list)
        for uid in user_ids:
            for followee in (
                self._persons[uid].following if uid in self._persons else []
            ):
                if followee in user_ids:
                    adj[uid].append(followee)
                    adj[followee].append(uid)
        visited: dict[int, bool] = {}
        components_list: list[list[int]] = []
        for uid in user_ids:
            if visited.get(uid):
                continue
            comp: list[int] = []
            stack = [uid]
            while stack:
                u = stack.pop()
                if visited.get(u):
                    continue
                visited[u] = True
                comp.append(u)
                for v in adj.get(u, []):
                    if not visited.get(v):
                        stack.append(v)
            if comp:
                components_list.append(comp)
        components_list.sort(key=len, reverse=True)
        labels = {}
        for i, comp in enumerate(components_list):
            cid = 0 if i == 0 else 1
            for u in comp:
                labels[u] = cid
        return labels

    def _get_candidate_posts(self, user_id: int) -> list[Post]:
        """按 feed_source 得到候选帖子列表：global=全站，following=仅关注者+自己的帖子。"""
        all_posts = list(self._posts.values())
        if self._feed_source != "following":
            return all_posts
        followees = set(
            self._persons[user_id].following if user_id in self._persons else []
        )
        allow_authors = followees | {user_id}
        return [p for p in all_posts if p.author_id in allow_authors]

    def _apply_polarization_mix(
        self, user_id: int, candidate_posts: list[Post], limit: int
    ) -> list[Post]:
        """
        当 polarization_mode=="follow_community" 时，按 within_community_ratio
        从同阵营与异阵营作者中混合取样，再按时间倒序；否则直接返回 candidate_posts。
        """
        if self._polarization_mode != "follow_community" or not candidate_posts:
            return candidate_posts
        labels = self._get_community_labels()
        viewer_community = labels.get(user_id, 0)
        same: list[Post] = [
            p for p in candidate_posts if labels.get(p.author_id, 0) == viewer_community
        ]
        other: list[Post] = [
            p for p in candidate_posts if labels.get(p.author_id, 0) != viewer_community
        ]
        rng = random.Random(self._random_seed if self._random_seed is not None else 0)
        n_same = max(0, round(self._within_community_ratio * limit))
        n_other = limit - n_same
        if n_same >= len(same) and n_other >= len(other):
            mixed = same + other
        else:
            shuffled_same = list(same)
            shuffled_other = list(other)
            rng.shuffle(shuffled_same)
            rng.shuffle(shuffled_other)
            mixed = shuffled_same[:n_same] + shuffled_other[:n_other]
        mixed.sort(key=lambda p: p.created_at, reverse=True)
        return mixed[:limit]

    def _append_event(
        self,
        action: str,
        sender_id: int,
        content: str | None = None,
        receiver_id: int | None = None,
        target_id: int | None = None,
    ) -> None:
        """将事件追加到 pending 缓冲。在 step() 末尾批量刷写到 replay DB。"""
        self._event_id += 1
        event = {
            "id": self._event_id,
            "step": self._step_counter,
            "t": self.t,
            "sender_id": sender_id,
            "action": action,
            "content": content,
            "receiver_id": receiver_id,
            "target_id": target_id,
        }
        self._pending_events.append(event)
        self._recent_events.append(dict(event))

    async def _flush_events(self) -> None:
        """将 pending 事件批量写入 social_media_event 表，然后清空缓冲。"""
        if self._replay_writer is None or not self._pending_events:
            return
        for event in self._pending_events:
            await self._replay_writer.write("social_media_event", event)
        self._pending_events.clear()

    async def _register_event_table(self) -> None:
        """注册统一事件表 schema。"""
        if self._replay_writer is None:
            return
        await self._replay_writer.register_table(_SOCIAL_MEDIA_EVENT_SCHEMA)
        await self._replay_writer.register_dataset(
            ReplayDatasetSpec(
                dataset_id="social_media.event",
                table_name=_SOCIAL_MEDIA_EVENT_SCHEMA.name,
                module_name=self.name,
                kind="event_stream",
                title="Social Media Event Stream",
                description="Event stream exported by SocialMediaSpace for posts, follows, likes, comments, and reposts.",
                entity_key="sender_id",
                step_key="step",
                time_key="t",
                default_order=["step", "id"],
                capabilities=["event_stream", "social_event"],
            ),
            _SOCIAL_MEDIA_EVENT_SCHEMA.columns,
        )
        get_logger().info("Registered social_media_event table")

    def _schedule_replay_task(self, coro) -> None:
        if self._replay_writer is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        asyncio.create_task(coro)

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Used by workspace init to generate .agentsociety/env_modules/social_media.json.
        """
        person_schema = SocialMediaPerson.model_json_schema()
        post_schema = Post.model_json_schema()
        comment_schema = Comment.model_json_schema()
        description = f"""{cls.__name__}: Social media platform environment module.

**Description:** Full-featured social media: posts, likes, follows, comments, feed recommendations.

**Initialization – pass initial data in memory:**
- persons (dict, optional): Map person_id (int) -> SocialMediaPerson-like dict (id, username, bio, created_at ISO string, followers_count, following_count, posts_count, optional camp_score).
- posts (dict, optional): Map post_id (int) -> Post-like dict (post_id, author_id, content, post_type "original"|"repost"|"comment", parent_id, created_at ISO, likes_count, reposts_count, comments_count, view_count, tags, topic_category).
- comments (dict, optional): Map post_id (int) -> list of Comment-like dicts (comment_id, post_id, author_id, content, created_at ISO, likes_count).
- follows (dict, optional): Map person_id (int) -> list of followed person_id (int).
- likes (dict, optional): Map person_id (int) -> list of liked post_id (int).
- feed_source ("global" | "following", optional): "global" = all posts; "following" = only followees + self. Default: "global".
- polarization_mode ("none" | "follow_community", optional): Default: "none".
- within_community_ratio (float), community_detection ("follow_components" | "parity"), random_seed (int): Optional.
- agent_id_name_pairs (list of [agent_id, name]): Explicit agent–user mapping; persons not in initial data are created with the given name.

**Initial data (example) :**

SocialMediaPerson (each key = person_id):
```json
{json.dumps(person_schema, indent=2)}
```

Post (each key = post_id):
```json
{json.dumps(post_schema, indent=2)}
```

Comment (each key = post_id, value = list of comments):
```json
{json.dumps(comment_schema, indent=2)}
```

Example payloads (ISO datetimes, keys may be int or string in JSON; constructor accepts both):
- persons: {{ 1: {{ "id": 1, "username": "alice", "bio": null, "created_at": "2024-08-01T00:00:00+00:00", "followers_count": 0, "following_count": 0, "posts_count": 0 }}, ... }}
- posts: {{ 1: {{ "post_id": 1, "author_id": 1, "content": "Hello.", "post_type": "original", "parent_id": null, "created_at": "2024-08-10T12:00:00+00:00", "likes_count": 0, "reposts_count": 0, "comments_count": 0, "view_count": 0, "tags": [], "topic_category": null }}, ... }}
- comments: {{ 1: [ {{ "comment_id": 1, "post_id": 1, "author_id": 2, "content": "A comment.", "created_at": "2024-08-10T12:30:00+00:00", "likes_count": 0 }} ] }}, ... }}
- follows: {{ 1: [2, 3], 2: [1] }}
- likes: {{ 1: [1, 2], 2: [1] }}

**Example initialization config:**
```json
{{
  "persons": {{ "1": {{ "id": 1, "username": "alice", "created_at": "2024-08-01T00:00:00" }}, "2": {{ "id": 2, "username": "bob", "created_at": "2024-08-01T00:00:00" }} }},
  "posts": {{ "1": {{ "post_id": 1, "author_id": 1, "content": "First post.", "post_type": "original", "created_at": "2024-08-10T12:00:00" }} }},
  "comments": {{}},
  "follows": {{ "1": [2], "2": [1] }},
  "likes": {{}},
  "feed_source": "global",
  "polarization_mode": "none"
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return (
            "Social media environment for posts, comments, likes, follows, and feeds."
        )

    @staticmethod
    def _norm_user_data(data: Any) -> dict[str, Any]:
        """Normalize user dict for SocialMediaPerson(...); accept ISO datetime strings."""
        d = dict(data)
        if "created_at" in d and isinstance(d["created_at"], str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        return d

    @staticmethod
    def _norm_post_data(data: Any) -> dict[str, Any]:
        """Normalize post dict for Post(...)."""
        d = dict(data)
        if "created_at" in d and isinstance(d["created_at"], str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        return d

    @staticmethod
    def _norm_comment_data(data: Any) -> dict[str, Any]:
        """Normalize comment dict for Comment(...)."""
        d = dict(data)
        if "created_at" in d and isinstance(d["created_at"], str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        return d

    @staticmethod
    def _norm_event_data(data: Any) -> dict[str, Any]:
        """Normalize replay event dict for observe timeline usage."""
        d = dict(data)
        if "t" in d and isinstance(d["t"], str):
            d["t"] = datetime.fromisoformat(d["t"])
        for key in ("id", "step", "sender_id", "receiver_id", "target_id"):
            if key in d and d[key] is not None:
                d[key] = int(d[key])
        return d

    @staticmethod
    def _dump_event_data(data: Any) -> dict[str, Any]:
        """Serialize replay event dict into a JSON-safe shape."""
        d = dict(data)
        if "t" in d and isinstance(d["t"], datetime):
            d["t"] = d["t"].isoformat()
        return d

    def _apply_initial_data(self) -> None:
        """Populate _persons, _posts, _comments from constructor initial data."""
        self._persons = {}
        for uid, data in (self._initial_persons or {}).items():
            self._persons[int(uid)] = SocialMediaPerson(**self._norm_user_data(data))
        self._posts = {}
        for pid, data in (self._initial_posts or {}).items():
            self._posts[int(pid)] = Post(**self._norm_post_data(data))
        # 将 follows 数据合入 SocialMediaPerson.following
        if self._initial_follows is not None:
            follower_counts: dict[int, int] = defaultdict(int)
            for uid, followee_ids in self._initial_follows.items():
                uid = int(uid)
                if uid in self._persons:
                    following = [int(x) for x in followee_ids]
                    self._persons[uid].following = following
                    self._persons[uid].following_count = len(following)
                    for followee_id in following:
                        follower_counts[followee_id] += 1

            for uid, person in self._persons.items():
                person.followers_count = follower_counts.get(uid, 0)
        self._comments = defaultdict(list)
        for post_id, comment_list in (self._initial_comments or {}).items():
            self._comments[int(post_id)] = [
                Comment(**self._norm_comment_data(c)) for c in comment_list
            ]
        if self._posts:
            self._next_post_id = max(self._posts.keys()) + 1
        else:
            self._next_post_id = 1
        all_comment_ids = [
            c.comment_id for comments in self._comments.values() for c in comments
        ]
        self._next_comment_id = max(all_comment_ids) + 1 if all_comment_ids else 1

        # 建立 person.post_ids 反向索引
        for pid, post in self._posts.items():
            if post.author_id in self._persons:
                self._persons[post.author_id].post_ids.append(pid)

        # 建立 person.comment_ids 反向索引
        for comment_list in self._comments.values():
            for c in comment_list:
                if c.author_id in self._persons:
                    self._persons[c.author_id].comment_ids.append(c.comment_id)

        # Apply likes (user_id -> [post_ids])
        for uid, post_ids in (self._initial_likes or {}).items():
            uid = int(uid)
            if uid in self._persons:
                liked = [int(x) for x in post_ids]
                self._persons[uid].liked_post_ids = liked
                # 同时更新 Post.liked_by
                for pid in liked:
                    if pid in self._posts:
                        if uid not in self._posts[pid].liked_by:
                            self._posts[pid].liked_by.append(uid)
                            self._posts[pid].likes_count = len(
                                self._posts[pid].liked_by
                            )

        get_logger().info(
            f"Applied initial data: {len(self._persons)} persons, {len(self._posts)} posts, "
            f"{sum(len(u.following) for u in self._persons.values())} follows, {len(self._comments)} post comments"
        )

    async def init(self, start_datetime: datetime):
        """
        Initialize the environment module. Uses in-memory initial data (persons, posts, ...) if provided; otherwise starts with empty state. Persistence is handled by external DB.
        """
        self.t = start_datetime
        has_initial = any(
            x is not None
            for x in (
                self._initial_persons,
                self._initial_posts,
                self._initial_comments,
                self._initial_follows,
                self._initial_likes,
            )
        )
        if has_initial:
            self._apply_initial_data()
        # 未传初始数据时保持空状态，持久化由外部数据库负责

        # 显式映射时：为 agent_id_name_pairs 中尚未存在的 id 创建对应用户
        if self._allowed_user_ids is not None:
            for aid in self._allowed_user_ids:
                if aid not in self._persons:
                    name = self._agent_names.get(aid, f"user_{aid}")
                    self._persons[aid] = SocialMediaPerson(id=aid, username=name)
                    get_logger().info(f"Created user for agent {aid} (username={name})")

        # 注册统一事件表
        if self._replay_writer is not None:
            await self._register_event_table()

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step

        :param tick: Number of ticks of this simulation step
        :param t: Current datetime after this step
        """
        self.t = t

        # 刷写 pending 事件到 replay DB
        await self._flush_events()

        # 写入 per-person 快照（声明式 _agent_state_columns）
        for person in self._persons.values():
            await self._write_agent_state(
                agent_id=person.id,
                step=self._step_counter,
                t=t,
                followers_count=person.followers_count,
                following_count=person.following_count,
                posts_count=person.posts_count,
            )

        self._step_counter += 1

    async def close(self):
        """Close the environment module. Data persistence is handled by external DB."""
        # 刷写剩余事件
        await self._flush_events()
        get_logger().info("SocialMediaSpace closed")

    def set_replay_writer(self, writer) -> None:
        super().set_replay_writer(writer)
        if writer is not None:
            self._schedule_replay_task(self._register_event_table())

    @staticmethod
    def _event_time_to_iso(event: dict) -> str | None:
        timestamp = event.get("t")
        if isinstance(timestamp, datetime):
            return timestamp.isoformat()
        if timestamp is None:
            return None
        return str(timestamp)

    def _iter_recent_events_desc(self) -> list[dict]:
        return sorted(
            self._recent_events,
            key=lambda event: (
                self._event_time_to_iso(event) or "",
                int(event.get("id", 0)),
            ),
            reverse=True,
        )

    def _build_profile_summary(self, user: SocialMediaPerson) -> dict:
        return {
            "user_id": user.id,
            "username": user.username,
            "bio": user.bio,
            "followers_count": user.followers_count,
            "following_count": user.following_count,
            "posts_count": user.posts_count,
        }

    def _build_recent_interactions(self, user_id: int, limit: int = 5) -> list[dict]:
        items = []
        for event in self._iter_recent_events_desc():
            action = event.get("action")
            actor_id = event.get("sender_id")
            post_id = event.get("target_id")
            if action not in {"like", "comment", "repost"}:
                continue
            if actor_id == user_id or post_id is None:
                continue
            post = self._posts.get(post_id)
            if post is None or post.author_id != user_id:
                continue
            actor = self._persons.get(actor_id)
            items.append(
                {
                    "action": action,
                    "created_at": self._event_time_to_iso(event),
                    "actor_id": actor_id,
                    "actor_username": actor.username if actor is not None else None,
                    "post_id": post_id,
                    "post_preview": post.content,
                    "content": event.get("content"),
                }
            )
            if len(items) >= limit:
                break
        return items

    def _build_recent_activity(self, user_id: int, limit: int = 5) -> list[dict]:
        items = []
        for event in self._iter_recent_events_desc():
            action = event.get("action")
            if event.get("sender_id") != user_id or action in {"follow", "unfollow"}:
                continue
            post_id = event.get("target_id")
            post = self._posts.get(post_id) if post_id is not None else None
            items.append(
                {
                    "action": action,
                    "created_at": self._event_time_to_iso(event),
                    "post_id": post_id,
                    "post_preview": (
                        post.content if post is not None else event.get("content")
                    ),
                    "content": event.get("content"),
                }
            )
            if len(items) >= limit:
                break
        return items

    def _build_social_updates(self, user_id: int, limit: int = 5) -> list[dict]:
        items = []
        for event in self._iter_recent_events_desc():
            action = event.get("action")
            actor_id = event.get("sender_id")
            target_user_id = event.get("receiver_id")
            if action not in {"follow", "unfollow"} or target_user_id is None:
                continue
            if actor_id != user_id and target_user_id != user_id:
                continue
            actor = self._persons.get(actor_id)
            target = self._persons.get(target_user_id)
            items.append(
                {
                    "action": action,
                    "created_at": self._event_time_to_iso(event),
                    "actor_id": actor_id,
                    "actor_username": actor.username if actor is not None else None,
                    "target_user_id": target_user_id,
                    "target_username": target.username if target is not None else None,
                    "direction": "outgoing" if actor_id == user_id else "incoming",
                }
            )
            if len(items) >= limit:
                break
        return items

    # @tool Methods

    @tool(readonly=True, kind="observe")
    async def observe_user(self, person_id: int) -> ObserveUserResponse:
        """
        观察用户当前状态

        用于 <observe> 指令，返回用户可见的社交媒体环境信息。

        :param person_id: 用户ID

        :returns: ObserveUserResponse 响应模型，包含用户状态和可用行为
        """
        user_id = person_id
        self._ensure_person_exists(user_id)
        user = self._persons[user_id]

        # 获取最近的 Feed
        candidate_posts = self._get_candidate_posts(user_id)
        if candidate_posts:
            if self._polarization_mode == "follow_community":
                recent_feed_posts = self._apply_polarization_mix(
                    user_id, candidate_posts, 5
                )
            else:
                recent_feed_posts = self._rec_engine.chronological(
                    candidate_posts, user_id, limit=5
                )
            recent_feed = [p.model_dump() for p in recent_feed_posts]
        else:
            recent_feed = []

        # 可用行为列表
        available_actions = [
            "create_post(author_id, content, tags=[]) - 发布帖子",
            "like_post(user_id, post_id) - 点赞帖子",
            "unlike_post(user_id, post_id) - 取消点赞",
            "follow_user(follower_id, followee_id) - 关注用户",
            "unfollow_user(follower_id, followee_id) - 取消关注",
            "view_post(user_id, post_id) - 查看帖子详情",
            "comment_on_post(user_id, post_id, content) - 评论帖子",
            "repost(user_id, post_id, comment='') - 转发帖子",
            "refresh_feed(user_id, algorithm='chronological', limit=20) - 刷新Feed",
            "search_posts(keyword, tags=[], limit=20) - 搜索帖子",
        ]

        return ObserveUserResponse(
            user_id=user.id,
            username=user.username,
            followers_count=user.followers_count,
            following_count=user.following_count,
            posts_count=user.posts_count,
            profile=self._build_profile_summary(user),
            recent_interactions=self._build_recent_interactions(user_id),
            recent_activity=self._build_recent_activity(user_id),
            social_updates=self._build_social_updates(user_id),
            recent_feed=recent_feed,
            available_actions=available_actions,
        )

    @tool(readonly=False)
    async def create_post(
        self, author_id: int, content: str, tags: list[str] | None = None
    ) -> CreatePostResponse:
        """
        Create a new original post (支持话题标签)

        :param author_id: ID of the author
        :param content: Content of the post
        :param tags: 话题标签列表，例如 ["guncontrol", "politics"]

        :returns: CreatePostResponse with post details
        """
        if tags is None:
            tags = []
        async with self._lock:
            self._ensure_person_exists(author_id)

            post_id = self._next_post_id
            self._next_post_id += 1
            post = Post(
                post_id=post_id,
                author_id=author_id,
                content=content,
                tags=tags,
                post_type="original",
                created_at=self.t,
            )

            self._posts[post_id] = post
            self._persons[author_id].posts_count += 1
            self._persons[author_id].post_ids.append(post_id)

            get_logger().info(
                f"User {author_id} created post {post_id} with tags {tags}"
            )

            self._append_event(
                "post", sender_id=author_id, content=content, target_id=post_id
            )

            return CreatePostResponse(
                post_id=post_id,
                author_id=author_id,
                content=content,
                tags=tags,
                created_at=post.created_at.isoformat(),
                post_type="original",
            )

    @tool(readonly=False)
    async def like_post(self, user_id: int, post_id: int) -> LikePostResponse:
        """
        Like a post

        :param user_id: ID of the user who likes
        :param post_id: ID of the post to like

        :returns: LikePostResponse with like details
        """
        async with self._lock:
            self._ensure_person_exists(user_id)

            if post_id not in self._posts:
                raise ValueError(f"Post {post_id} does not exist")

            post = self._posts[post_id]
            person = self._persons[user_id]

            if user_id in post.liked_by:
                raise ValueError(f"User {user_id} has already liked post {post_id}")

            post.liked_by.append(user_id)
            post.likes_count = len(post.liked_by)
            person.liked_post_ids.append(post_id)

            get_logger().info(f"User {user_id} liked post {post_id}")

            self._append_event("like", sender_id=user_id, target_id=post_id)

            return LikePostResponse(
                post_id=post_id,
                user_id=user_id,
                total_likes=self._posts[post_id].likes_count,
            )

    @tool(readonly=False)
    async def unlike_post(self, user_id: int, post_id: int) -> UnlikePostResponse:
        """
        Unlike a post

        :param user_id: ID of the user who unlikes
        :param post_id: ID of the post to unlike

        :returns: UnlikePostResponse with unlike details
        """
        async with self._lock:
            self._ensure_person_exists(user_id)

            if post_id not in self._posts:
                raise ValueError(f"Post {post_id} does not exist")

            post = self._posts[post_id]
            person = self._persons[user_id]

            if user_id not in post.liked_by:
                raise ValueError(f"User {user_id} has not liked post {post_id}")

            post.liked_by.remove(user_id)
            post.likes_count = len(post.liked_by)
            person.liked_post_ids.remove(post_id)

            get_logger().info(f"User {user_id} unliked post {post_id}")

            self._append_event("unlike", sender_id=user_id, target_id=post_id)

            return UnlikePostResponse(
                post_id=post_id,
                user_id=user_id,
                total_likes=self._posts[post_id].likes_count,
            )

    @tool(readonly=False)
    async def follow_user(
        self, follower_id: int, followee_id: int
    ) -> FollowUserResponse:
        """
        Follow a user

        :param follower_id: ID of the follower
        :param followee_id: ID of the user to follow

        :returns: FollowUserResponse with follow details
        """
        async with self._lock:
            self._ensure_person_exists(follower_id)
            self._ensure_person_exists(followee_id)

            if follower_id == followee_id:
                raise ValueError(
                    f"Failed to follow: user {follower_id} cannot follow themselves"
                )

            if followee_id in self._persons[follower_id].following:
                raise ValueError(
                    f"User {follower_id} is already following user {followee_id}"
                )

            self._persons[follower_id].following.append(followee_id)
            self._persons[follower_id].following_count += 1
            self._persons[followee_id].followers_count += 1

            get_logger().info(f"User {follower_id} followed user {followee_id}")

            self._append_event("follow", sender_id=follower_id, receiver_id=followee_id)

            return FollowUserResponse(
                follower_id=follower_id,
                followee_id=followee_id,
                follower_following_count=self._persons[follower_id].following_count,
                followee_followers_count=self._persons[followee_id].followers_count,
            )

    @tool(readonly=False)
    async def unfollow_user(
        self, follower_id: int, followee_id: int
    ) -> UnfollowUserResponse:
        """
        Unfollow a user

        :param follower_id: ID of the follower
        :param followee_id: ID of the user to unfollow

        :returns: UnfollowUserResponse with unfollow details
        """
        async with self._lock:
            self._ensure_person_exists(follower_id)
            self._ensure_person_exists(followee_id)

            if followee_id not in self._persons[follower_id].following:
                raise ValueError(
                    f"User {follower_id} is not following user {followee_id}"
                )

            self._persons[follower_id].following.remove(followee_id)
            self._persons[follower_id].following_count -= 1
            self._persons[followee_id].followers_count -= 1

            get_logger().info(f"User {follower_id} unfollowed user {followee_id}")

            self._append_event(
                "unfollow", sender_id=follower_id, receiver_id=followee_id
            )

            return UnfollowUserResponse(
                follower_id=follower_id,
                followee_id=followee_id,
                follower_following_count=self._persons[follower_id].following_count,
                followee_followers_count=self._persons[followee_id].followers_count,
            )

    @tool(readonly=False)
    async def view_post(self, user_id: int, post_id: int) -> ViewPostResponse:
        """
        View a post (increments view count)

        :param user_id: ID of the user viewing
        :param post_id: ID of the post to view

        :returns: ViewPostResponse with post details
        """
        async with self._lock:
            self._ensure_person_exists(user_id)

            if post_id not in self._posts:
                raise ValueError(f"Failed to view: post {post_id} does not exist")

            post = self._posts[post_id]
            post.view_count += 1

            get_logger().debug(f"User {user_id} viewed post {post_id}")

            return ViewPostResponse(
                post_id=post.post_id,
                author_id=post.author_id,
                content=post.content,
                post_type=post.post_type,
                likes_count=post.likes_count,
                comments_count=post.comments_count,
                reposts_count=post.reposts_count,
                view_count=post.view_count,
                created_at=post.created_at.isoformat(),
                tags=post.tags,
                topic_category=post.topic_category,
            )

    @tool(readonly=False)
    async def comment_on_post(
        self, user_id: int, post_id: int, content: str
    ) -> CommentOnPostResponse:
        """
        Comment on a post

        :param user_id: ID of the commenter
        :param post_id: ID of the post to comment on
        :param content: Comment content

        :returns: CommentOnPostResponse with comment details
        """
        async with self._lock:
            self._ensure_person_exists(user_id)

            if post_id not in self._posts:
                raise ValueError(f"Failed to comment: post {post_id} does not exist")

            comment_id = self._next_comment_id
            self._next_comment_id += 1

            comment = Comment(
                comment_id=comment_id,
                post_id=post_id,
                author_id=user_id,
                content=content,
                created_at=self.t,
            )

            self._comments[post_id].append(comment)
            self._posts[post_id].comments_count += 1
            self._persons[user_id].comment_ids.append(comment_id)

            get_logger().info(f"User {user_id} commented on post {post_id}")

            self._append_event(
                "comment", sender_id=user_id, content=content, target_id=post_id
            )

            return CommentOnPostResponse(
                comment_id=comment_id,
                post_id=post_id,
                user_id=user_id,
                content=content,
                total_comments=self._posts[post_id].comments_count,
            )

    @tool(readonly=False)
    async def repost(
        self, user_id: int, post_id: int, comment: str = ""
    ) -> RepostResponse:
        """
        Repost a post (with optional comment)

        :param user_id: ID of the user reposting
        :param post_id: ID of the post to repost
        :param comment: Optional comment on the repost

        :returns: RepostResponse with repost details
        """
        async with self._lock:
            self._ensure_person_exists(user_id)

            if post_id not in self._posts:
                raise ValueError(f"Failed to repost: post {post_id} does not exist")

            new_post_id = self._next_post_id
            self._next_post_id += 1

            repost_content = comment if comment else f"repost {post_id}"

            repost_post = Post(
                post_id=new_post_id,
                author_id=user_id,
                content=repost_content,
                post_type="repost",
                parent_id=post_id,
                created_at=self.t,
            )

            self._posts[new_post_id] = repost_post
            self._posts[post_id].reposts_count += 1
            self._persons[user_id].posts_count += 1
            self._persons[user_id].post_ids.append(new_post_id)

            get_logger().info(
                f"User {user_id} reposted post {post_id} as {new_post_id}"
            )

            self._append_event(
                "repost", sender_id=user_id, content=repost_content, target_id=post_id
            )

            return RepostResponse(
                new_post_id=new_post_id,
                original_post_id=post_id,
                user_id=user_id,
                comment=comment,
                original_reposts_count=self._posts[post_id].reposts_count,
            )

    @tool(readonly=True)
    async def refresh_feed(
        self, user_id: int, algorithm: str = "chronological", limit: int = 20
    ) -> RefreshFeedResponse:
        """
        刷新用户Feed流（贴文推荐流 Feed Recommendation）

        **注意**: 这是贴文流推荐,不是物品推荐(Item Recommendation)
        - 贴文推荐: 社交媒体的动态内容流(如Twitter/微博Timeline)
        - 物品推荐: 电商/电影等静态物品推荐(应使用独立的API)

        :param user_id: 用户ID
        :param algorithm: 贴文推荐算法 - "chronological": 时间倒序 - "reddit_hot": Reddit热度排序 - "twitter_ranking": Twitter综合排序(考虑社交关系) - "random": 随机推荐 - "mf" / "model": 预训练推荐模型（需在构造时传入 recommendation_model_path）
        :param limit: 返回贴文数量

        :returns: (context_dict, answer_string) 元组
        """
        self._ensure_person_exists(user_id)

        # 按 feed_source 得到候选帖子（global=全站，following=关注+自己）
        candidate_posts = self._get_candidate_posts(user_id)

        if not candidate_posts:
            return RefreshFeedResponse(
                user_id=user_id, algorithm=algorithm, posts=[], count=0
            )

        # 极化混合：若 polarization_mode=="follow_community"，按 within_community_ratio 混合同/异阵营
        if self._polarization_mode == "follow_community":
            candidate_posts = self._apply_polarization_mix(
                user_id, candidate_posts, limit
            )
            # 混合后已按时间倒序；若算法非 chronological 则再按该算法重排
            if algorithm == "chronological":
                recommended_posts = candidate_posts
            elif algorithm == "reddit_hot":
                recommended_posts = self._rec_engine.reddit_hot(
                    candidate_posts, user_id, limit
                )
            elif algorithm == "twitter_ranking":
                recommended_posts = self._rec_engine.twitter_ranking(
                    candidate_posts,
                    user_id,
                    limit,
                    follows={uid: u.following for uid, u in self._persons.items()},
                )
            elif algorithm == "random":
                rng = random.Random(self._random_seed)
                if len(candidate_posts) <= limit:
                    recommended_posts = list(candidate_posts)
                else:
                    recommended_posts = rng.sample(candidate_posts, limit)
            elif (
                algorithm in ("mf", "model")
                or algorithm == self._rec_engine.get_model_algorithm_name()
            ):
                recommended_posts = self._rec_engine.model_recommend(
                    candidate_posts, user_id, limit, exclude_post_ids=None
                )
            else:
                recommended_posts = candidate_posts
        else:
            # 无极化：直接按算法排序
            if algorithm == "chronological":
                recommended_posts = self._rec_engine.chronological(
                    candidate_posts, user_id, limit
                )
            elif algorithm == "reddit_hot":
                recommended_posts = self._rec_engine.reddit_hot(
                    candidate_posts, user_id, limit
                )
            elif algorithm == "twitter_ranking":
                recommended_posts = self._rec_engine.twitter_ranking(
                    candidate_posts,
                    user_id,
                    limit,
                    follows={uid: u.following for uid, u in self._persons.items()},
                )
            elif algorithm == "random":
                if self._random_seed is not None:
                    rng = random.Random(self._random_seed)
                    recommended_posts = (
                        rng.sample(candidate_posts, limit)
                        if len(candidate_posts) > limit
                        else list(candidate_posts)
                    )
                else:
                    recommended_posts = self._rec_engine.random_recommend(
                        candidate_posts, user_id, limit
                    )
            elif (
                algorithm in ("mf", "model")
                or algorithm == self._rec_engine.get_model_algorithm_name()
            ):
                # 预训练推荐模型（如 MF）；未加载模型时 model_recommend 内部回退为时间序
                recommended_posts = self._rec_engine.model_recommend(
                    candidate_posts, user_id, limit, exclude_post_ids=None
                )
            else:
                get_logger().warning(
                    f"Unknown algorithm '{algorithm}', using chronological"
                )
                recommended_posts = self._rec_engine.chronological(
                    candidate_posts, user_id, limit
                )

        get_logger().info(
            f"User {user_id} refreshed feed with algorithm '{algorithm}', got {len(recommended_posts)} posts"
        )

        return RefreshFeedResponse(
            user_id=user_id,
            algorithm=algorithm,
            posts=[p.model_dump() for p in recommended_posts],
            count=len(recommended_posts),
        )

    @tool(readonly=True)
    async def search_posts(
        self,
        keyword: str,
        tags: list[str] | None = None,
        limit: int = 20,
        sort_by: str = "time",  # "time", "relevance", "popularity"
    ) -> SearchPostsResponse:
        """
        搜索贴文

        :param keyword: 关键词（在content和tags中搜索）
        :param tags: 指定话题标签过滤
        :param limit: 返回数量
        :param sort_by: 排序方式 - "time": 时间倒序（默认） - "relevance": 相关度（关键词出现次数） - "popularity": 热度（likes + comments + reposts）

        :returns: 匹配的贴文列表
        """
        if tags is None:
            tags = []
        keyword_lower = keyword.lower()
        matched_posts = []

        # 搜索逻辑
        for post in self._posts.values():
            # 标签过滤
            if tags and not any(tag in post.tags for tag in tags):
                continue

            # 关键词匹配
            in_content = keyword_lower in post.content.lower()
            in_tags = any(keyword_lower in tag.lower() for tag in post.tags)

            if in_content or in_tags:
                # 计算相关度分数（用于排序）
                relevance_score = 0
                if in_content:
                    relevance_score += post.content.lower().count(keyword_lower)
                if in_tags:
                    relevance_score += 10  # 标签匹配权重高

                matched_posts.append(
                    {
                        "post": post,
                        "relevance_score": relevance_score,
                        "popularity_score": post.likes_count
                        + post.comments_count * 2
                        + post.reposts_count * 3,
                    }
                )

        # 排序
        if sort_by == "time":
            matched_posts.sort(key=lambda x: x["post"].created_at, reverse=True)
        elif sort_by == "relevance":
            matched_posts.sort(key=lambda x: x["relevance_score"], reverse=True)
        elif sort_by == "popularity":
            matched_posts.sort(key=lambda x: x["popularity_score"], reverse=True)

        # 限制数量
        result_posts = [item["post"] for item in matched_posts[:limit]]

        get_logger().info(
            f"Search '{keyword}' with tags {tags}: found {len(matched_posts)} posts, returning {len(result_posts)}"
        )

        return SearchPostsResponse(
            keyword=keyword,
            tags=tags,
            sort_by=sort_by,
            posts=[p.model_dump() for p in result_posts],
            count=len(result_posts),
            total_matched=len(matched_posts),
        )

    # 一些辅助函数

    def _ensure_person_exists(self, user_id: int) -> None:
        """
        若 user_id 不在当前用户集中则创建对应用户。
        当初始化时传入了 agent_id_name_pairs 时，仅允许该集合内的 id；否则允许任意 id 并按需创建。
        """
        if self._allowed_user_ids is not None and user_id not in self._allowed_user_ids:
            raise ValueError(
                f"User id {user_id} is not in the allowed agent set (agent_id_name_pairs). "
                f"Allowed ids: {sorted(self._allowed_user_ids)}"
            )
        if user_id not in self._persons:
            name = self._agent_names.get(user_id, f"user_{user_id}")
            self._persons[user_id] = SocialMediaPerson(id=user_id, username=name)
            get_logger().info(f"Auto-created user {user_id} (username={name})")


__all__ = ["SocialMediaSpace"]
