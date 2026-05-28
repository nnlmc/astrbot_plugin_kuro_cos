from __future__ import annotations

import asyncio
import importlib
import random
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".flv", ".mkv", ".m3u8"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
KURO_MEDIA_HOST_KEYWORDS = ("kurobbs.com", "kurogame.com", "aki-game.com")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
)
DEFAULT_DEV_CODE = "H0O9l04JUG341k5UpUTMNpnGawC5Qt9p"
DEFAULT_DISTINCT_ID = "195be91535f592-0915a368d4173f-4c657b58-1327104-195be9153601740"
URL_RE = re.compile(r"https?://[^\s'\"<>，。！？、）)\]}]+", re.IGNORECASE)
POST_TEXT_KEYS = (
    "postTitle",
    "title",
    "subject",
    "content",
    "summary",
    "desc",
    "description",
    "postContent",
    "postDetail",
    "textContent",
    "richContent",
    "articleContent",
    "markdownContent",
    "topicContent",
)
REPOST_FORBIDDEN_KEYWORDS = (
    "禁止搬运",
    "禁止转载",
    "禁止转发",
    "禁止转帖",
    "禁止二传",
    "禁止二次上传",
    "禁止二改",
    "禁止盗图",
    "严禁搬运",
    "严禁转载",
    "严禁转发",
    "严禁二传",
    "请勿搬运",
    "请勿转载",
    "请勿转发",
    "请勿二传",
    "请勿二改",
    "勿搬运",
    "勿转载",
    "勿转发",
    "勿二传",
    "不要搬运",
    "不要转载",
    "不要转发",
    "不要二传",
    "请不要搬运",
    "请不要转载",
    "请不要转发",
    "不得搬运",
    "不得转载",
    "不得转发",
    "不得二传",
    "不许搬运",
    "不许转载",
    "不许转发",
    "不许二传",
    "不准搬运",
    "不准转载",
    "不准转发",
    "不准二传",
    "不能搬运",
    "不能转载",
    "不能转发",
    "不能二传",
    "不可搬运",
    "不可转载",
    "不可转发",
    "不可二传",
    "不允许搬运",
    "不允许转载",
    "不允许转发",
    "不允许二传",
    "谢绝搬运",
    "谢绝转载",
    "谢绝转发",
    "拒绝搬运",
    "拒绝转载",
    "拒绝转发",
    "婉拒搬运",
    "婉拒转载",
    "未经授权转载",
    "未经授权搬运",
    "未经授权转发",
    "未经授权不得转载",
    "未经授权请勿转载",
    "未经允许转载",
    "未经允许搬运",
    "未经允许转发",
    "未经许可转载",
    "未经许可搬运",
    "未经许可转发",
    "未授权转载",
    "未授权搬运",
    "无授权转载",
    "无授权搬运",
    "擅自转载",
    "擅自搬运",
    "私自转载",
    "私自搬运",
    "不授权转载",
    "不授权搬运",
    "不开放转载",
    "不开放搬运",
    "禁搬运",
    "禁转载",
    "禁转",
    "禁二传",
    "禁二改",
    "禁止任何形式转载",
    "禁止任何形式搬运",
    "禁止任何形式转发",
    "do not repost",
    "don't repost",
    "dont repost",
    "please do not repost",
    "please don't repost",
    "no repost",
    "no re-post",
    "repost prohibited",
    "reposting prohibited",
    "repost forbidden",
    "unauthorized repost",
    "unauthorised repost",
    "do not reupload",
    "do not re-upload",
    "no reupload",
    "no re-upload",
    "reupload prohibited",
    "re-upload prohibited",
    "転載禁止",
    "無断転載禁止",
    "無断使用禁止",
    "無断転載お断り",
    "無断転載は禁止",
    "二次配布禁止",
    "무단전재금지",
    "무단배포금지",
)


@dataclass(frozen=True)
class MediaItem:
    url: str
    kind: str


@dataclass(frozen=True)
class KuroPost:
    post_id: str
    title: str 
    summary: str
    author: str
    url: str
    media: tuple[MediaItem, ...]


def _get_config_value(config: AstrBotConfig | None, key: str, default: Any) -> Any:
    if config is None:
        return default
    try:
        return config.get(key, default)
    except Exception:
        return default


def _clean_text(value: Any, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_from_value(child) for child in value.values())
    if isinstance(value, list):
        return " ".join(_text_from_value(child) for child in value)
    return ""


def _collect_post_text(node: dict[str, Any]) -> str:
    return " ".join(_text_from_value(node.get(key)) for key in POST_TEXT_KEYS if key in node)


def _normalize_for_keyword_match(text: str) -> str:
    text = text.lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _has_repost_forbidden_text(node: dict[str, Any]) -> bool:
    text = _collect_post_text(node)
    if not text:
        return False
    compact_text = _normalize_for_keyword_match(text)
    for keyword in REPOST_FORBIDDEN_KEYWORDS:
        if keyword.lower() in text.lower() or _normalize_for_keyword_match(keyword) in compact_text:
            return True
    return False


def _normalize_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip().replace("\\/", "/").rstrip(".,;:!?，。；：！？、")
    if not url.startswith(("http://", "https://")):
        return None
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    return url


def _url_suffix(url: str) -> str:
    return Path(urlparse(url).path.lower()).suffix


def _looks_like_kuro_media(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == key or host.endswith(f".{key}") for key in KURO_MEDIA_HOST_KEYWORDS)


def _dedupe_media(items: list[MediaItem]) -> tuple[MediaItem, ...]:
    seen: set[str] = set()
    result: list[MediaItem] = []
    for item in items:
        key = item.url.split("?", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def _append_media_url(media: list[MediaItem], raw_url: Any, forced_kind: str | None = None):
    url = _normalize_url(raw_url)
    if not url or not _looks_like_kuro_media(url):
        return
    suffix = _url_suffix(url)
    if forced_kind == "image" and suffix in VIDEO_EXTENSIONS:
        return
    if forced_kind == "video" and suffix in IMAGE_EXTENSIONS:
        return
    kind = forced_kind
    if kind is None:
        if suffix in IMAGE_EXTENSIONS:
            kind = "image"
        elif suffix in VIDEO_EXTENSIONS:
            kind = "video"
    if kind:
        media.append(MediaItem(url=url, kind=kind))


def _extract_urls_from_text(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [match.rstrip(".,;:!?，。；：！？、") for match in URL_RE.findall(value)]


def _extract_from_media_container(value: Any, forced_kind: str | None = None) -> list[MediaItem]:
    media: list[MediaItem] = []

    def visit(item: Any):
        if isinstance(item, str):
            if item.startswith(("http://", "https://")):
                _append_media_url(media, item, forced_kind)
            else:
                for url in _extract_urls_from_text(item):
                    _append_media_url(media, url, forced_kind)
            return
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if isinstance(item, dict):
            for key in ("url", "imgUrl", "imageUrl", "picUrl", "videoUrl", "coverUrl", "resourceUrl", "src", "path"):
                if key in item:
                    _append_media_url(media, item.get(key), forced_kind)
            for key in ("urls", "images", "imgs", "videos", "resources", "content"):
                if key in item:
                    visit(item.get(key))

    visit(value)
    return media


def _extract_post_media(node: dict[str, Any]) -> tuple[MediaItem, ...]:
    media: list[MediaItem] = []

    for key in ("imgContent", "imageContent", "images", "imgs", "picList", "imageList"):
        if key in node:
            media.extend(_extract_from_media_container(node.get(key), "image"))

    for key in ("videoContent", "video", "videos", "videoInfo", "videoList", "videoUrl"):
        if key in node:
            media.extend(_extract_from_media_container(node.get(key), "video"))

    for key in ("postContent", "content", "summary", "desc", "postDetail"):
        for url in _extract_urls_from_text(node.get(key)):
            _append_media_url(media, url)

    return _dedupe_media(media)


def _post_from_node(node: dict[str, Any]) -> KuroPost | None:
    if _has_repost_forbidden_text(node):
        return None

    post_id = str(node.get("postId") or node.get("post_id") or node.get("id") or "").strip()
    title = _clean_text(node.get("postTitle") or node.get("title") or node.get("subject") or "鸣潮 COS", 80)
    summary = _clean_text(node.get("content") or node.get("summary") or node.get("desc") or node.get("postContent") or "", 160)
    author_node = node.get("user") or node.get("author") or node.get("postUser") or {}
    author = ""
    if isinstance(author_node, dict):
        author = _clean_text(author_node.get("userName") or author_node.get("nickname") or author_node.get("name") or "", 40)
    author = author or _clean_text(node.get("userName") or node.get("nickname") or "库街区用户", 40)
    media = _extract_post_media(node)
    if not media:
        return None
    url = f"https://www.kurobbs.com/mc/post/{post_id}" if post_id else "https://www.kurobbs.com/"
    return KuroPost(post_id=post_id, title=title, summary=summary, author=author, url=url, media=media)


def _extract_post_list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("postList"), list):
        return [item for item in data["postList"] if isinstance(item, dict)]
    if isinstance(payload.get("postList"), list):
        return [item for item in payload["postList"] if isinstance(item, dict)]
    return []


@register(
    "astrbot_plugin_kuro_cos",
    "Copilot",
    "获取鸣潮库街区 COS 板块图片和视频，并由机器人发送。",
    "0.2.0",
)
class KuroCosPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config
        self.output_dir = Path("data") / "plugins_data" / "astrbot_plugin_kuro_cos" / "media"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Semaphore(1)
        self._recent_post_ids: deque[str] = deque(maxlen=80)
        self._recall_tasks: set[asyncio.Task[None]] = set()

    @filter.command("鸣潮cos")
    async def kuro_cos_command(self, event: AstrMessageEvent):
        """获取鸣潮库街区 COS 图片/视频。"""
        async with self._lock:
            posts = await self._fetch_random_posts()
            if not posts:
                yield event.plain_result("没找到包含 COS 图片/视频的库街区内容。")
                event.stop_event()
                return

            post = posts[0]
            self._remember_post(post)
            chain, local_paths = await self._build_post_chain(post)
            sent_by_direct_send = False
            try:
                if self._recall_after_send_enabled():
                    sent_by_direct_send, sent_message_ids = await self._send_chain_and_collect_ids(event, chain)
                    if sent_by_direct_send:
                        if sent_message_ids:
                            self._schedule_recall(event, sent_message_ids)
                        return
                yield event.chain_result(chain)
            finally:
                if sent_by_direct_send:
                    event.stop_event()
                if bool(_get_config_value(self.config, "delete_after_send", True)):
                    self._cleanup_local_files(local_paths)

        event.stop_event()

    def _recall_after_send_enabled(self) -> bool:
        return bool(_get_config_value(self.config, "recall_after_send", False))

    def _recall_delay_seconds(self) -> float:
        try:
            delay = float(_get_config_value(self.config, "recall_delay_seconds", 60.0))
        except (TypeError, ValueError):
            delay = 60.0
        return max(0.0, min(delay, 120.0))

    async def _send_chain_and_collect_ids(self, event: AstrMessageEvent, chain: list[Any]) -> tuple[bool, list[str]]:
        bot = getattr(event, "bot", None)
        if bot is None:
            self._debug("当前平台不支持自动撤回：缺少 bot 客户端")
            return False, []

        try:
            event_module = importlib.import_module("astrbot.api.event")
            aiocqhttp_module = importlib.import_module(
                "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event"
            )
            message_chain_cls = getattr(event_module, "MessageChain")
            aiocqhttp_event_cls = getattr(aiocqhttp_module, "AiocqhttpMessageEvent")
        except Exception as exc:
            self._debug(f"当前环境无法加载 aiocqhttp 发送组件，跳过自动撤回直发：{exc!r}")
            return False, []

        parse_onebot_json = getattr(aiocqhttp_event_cls, "_parse_onebot_json", None)
        if parse_onebot_json is None:
            self._debug("当前 AstrBot 版本缺少 OneBot 消息转换接口，跳过自动撤回直发")
            return False, []

        is_group = bool(event.get_group_id())
        session_id = event.get_group_id() if is_group else event.get_sender_id()
        if not str(session_id).isdigit():
            self._debug(f"当前会话 ID 不可用于 OneBot 发送：{session_id}")
            return False, []

        sent_message_ids: list[str] = []
        sent_any = False
        try:
            for message_chain in self._split_chain_for_recall(message_chain_cls(chain=chain)):
                result = await self._send_onebot_chain(bot, message_chain, parse_onebot_json, is_group, str(session_id))
                sent_any = True
                message_id = self._extract_sent_message_id(result)
                if message_id:
                    sent_message_ids.append(message_id)
                await asyncio.sleep(0.5)
            if sent_any and not sent_message_ids:
                self._debug("已直发消息，但平台未返回 message_id，无法自动撤回")
            return sent_any, sent_message_ids
        except Exception as exc:
            if sent_any:
                logger.warning(f"[kuro_cos] 自动撤回直发部分成功，跳过普通发送以避免重复：{exc!r}")
                return True, sent_message_ids
            logger.warning(f"[kuro_cos] 自动撤回直发失败，改用普通发送：{exc!r}")
            return False, []

    async def _send_onebot_chain(self, bot: Any, message_chain: Any, parse_onebot_json: Any, is_group: bool, session_id: str) -> Any:
        nodes_cls = getattr(Comp, "Nodes", None)
        node_cls = getattr(Comp, "Node", None)
        if len(message_chain.chain) == 1:
            item = message_chain.chain[0]
            if nodes_cls is not None and isinstance(item, nodes_cls):
                payload = await item.to_dict()
                if is_group:
                    payload["group_id"] = session_id
                    return await bot.call_action("send_group_forward_msg", **payload)
                payload["user_id"] = session_id
                return await bot.call_action("send_private_forward_msg", **payload)
            if node_cls is not None and isinstance(item, node_cls) and nodes_cls is not None:
                nodes = nodes_cls([item])
                return await self._send_onebot_chain(bot, message_chain.derive([nodes]), parse_onebot_json, is_group, session_id)

        messages = await parse_onebot_json(message_chain)
        if not messages:
            return None
        if is_group:
            return await bot.send_group_msg(group_id=int(session_id), message=messages)
        return await bot.send_private_msg(user_id=int(session_id), message=messages)

    def _split_chain_for_recall(self, message_chain: Any) -> list[Any]:
        separate_types = tuple(
            item for item in (getattr(Comp, "Node", None), getattr(Comp, "Nodes", None), getattr(Comp, "File", None)) if item
        )
        if not separate_types or not any(isinstance(item, separate_types) for item in message_chain.chain):
            return [message_chain]

        chunks: list[Any] = []
        for item in message_chain.chain:
            if isinstance(item, separate_types):
                chunks.append(message_chain.derive([item]))
            elif chunks and not isinstance(chunks[-1].chain[0], separate_types):
                chunks[-1].chain.append(item)
            else:
                chunks.append(message_chain.derive([item]))
        return chunks

    @staticmethod
    def _extract_sent_message_id(result: Any) -> str | None:
        if isinstance(result, dict):
            value = result.get("message_id") or result.get("msg_id") or result.get("id")
            return str(value) if value is not None else None
        value = getattr(result, "message_id", None) or getattr(result, "msg_id", None) or getattr(result, "id", None)
        return str(value) if value is not None else None

    def _schedule_recall(self, event: AstrMessageEvent, message_ids: list[str]):
        delay = self._recall_delay_seconds()
        task = asyncio.create_task(self._recall_messages_later(event, message_ids, delay))
        self._recall_tasks.add(task)
        task.add_done_callback(self._recall_tasks.discard)

    async def _recall_messages_later(self, event: AstrMessageEvent, message_ids: list[str], delay: float):
        await asyncio.sleep(delay)
        bot = getattr(event, "bot", None)
        if bot is None:
            return
        for message_id in message_ids:
            try:
                await bot.call_action("delete_msg", message_id=int(message_id) if str(message_id).isdigit() else message_id)
                self._debug(f"已撤回消息 message_id={message_id}")
            except Exception as exc:
                logger.warning(f"[kuro_cos] 撤回消息失败 message_id={message_id} error={exc!r}")

    async def _fetch_random_posts(self) -> list[KuroPost]:
        payloads: list[Any] = []
        timeout = float(_get_config_value(self.config, "request_timeout", 15.0))
        base = str(_get_config_value(self.config, "api_base", "https://api.kurobbs.com")).rstrip("/")
        endpoint = str(_get_config_value(self.config, "list_endpoint", "/forum/list"))
        page_size = max(1, int(_get_config_value(self.config, "default_page_size", 20)))
        game_id = int(_get_config_value(self.config, "game_id", 3))
        forum_id = int(_get_config_value(self.config, "forum_id", 17))
        search_type = int(_get_config_value(self.config, "search_type", 3))
        random_page_max = max(1, int(_get_config_value(self.config, "random_page_max", 500)))
        request_rounds = max(1, int(_get_config_value(self.config, "request_rounds", 50)))
        dev_code = str(_get_config_value(self.config, "dev_code", DEFAULT_DEV_CODE))
        distinct_id = str(_get_config_value(self.config, "distinct_id", DEFAULT_DISTINCT_ID))

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": "https://www.kurobbs.com",
            "Referer": "https://www.kurobbs.com/",
            "User-Agent": DEFAULT_USER_AGENT,
            "devCode": dev_code,
            "distinct_id": distinct_id,
            "source": "h5",
            "token": "",
            "version": "2.4.4",
        }
        url = endpoint if endpoint.startswith("http") else f"{base}/{endpoint.lstrip('/')}"
        page_indexes = random.sample(range(1, random_page_max + 1), k=min(request_rounds, random_page_max))

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            for page_index in page_indexes:
                body = {
                    "gameId": game_id,
                    "forumId": forum_id,
                    "searchType": search_type,
                    "pageIndex": page_index,
                    "pageSize": page_size,
                }
                try:
                    response = await client.post(url, data=body)
                    response.raise_for_status()
                    payloads.append(response.json())
                    self._debug(f"列表接口完成 pageIndex={page_index}")
                except Exception as exc:
                    self._debug(f"列表接口失败 url={url} pageIndex={page_index} error={exc!r}")

        posts: list[KuroPost] = []
        seen: set[str] = set()
        for payload in payloads:
            for node in _extract_post_list(payload):
                post = _post_from_node(node)
                if not post:
                    continue
                key = post.post_id or post.url or post.title
                if key in seen or key in self._recent_post_ids:
                    continue
                seen.add(key)
                posts.append(post)

        random.shuffle(posts)
        for post in posts:
            shuffled_media = list(post.media)
            random.shuffle(shuffled_media)
            yield_post = KuroPost(
                post_id=post.post_id,
                title=post.title,
                summary=post.summary,
                author=post.author,
                url=post.url,
                media=tuple(shuffled_media),
            )
            self._debug(f"候选帖子 post_id={yield_post.post_id} media={len(yield_post.media)}")
            return [yield_post]

        self._debug("本轮没有新的正文媒体帖子")
        return []

    async def _build_post_chain(self, post: KuroPost) -> tuple[list[Any], list[str]]:
        max_media = int(_get_config_value(self.config, "max_media_per_post", 8))
        download_media = bool(_get_config_value(self.config, "download_media", True))
        use_forward = bool(
            _get_config_value(self.config, "use_forward", _get_config_value(self.config, "forward_enable", True))
        )
        node_name = str(
            _get_config_value(self.config, "forward_sender_name", _get_config_value(self.config, "forward_node_name", "库街区COS"))
        ).strip() or "库街区COS"
        node_uin = str(
            _get_config_value(self.config, "forward_sender_id", _get_config_value(self.config, "forward_node_uin", "10000"))
        ).strip() or "10000"
        first_node_text = f"鸣潮 COS\n{post.title}\n作者：{post.author}\n{post.url}"
        text = f"鸣潮 COS\n{post.title}\n作者：{post.author}\n{post.url}"
        if post.summary:
            text += f"\n{post.summary}"
            first_node_text += f"\n{post.summary}"

        chain: list[Any] = [Comp.Plain(text)]
        forward_nodes: list[Any] = [Comp.Node(uin=node_uin, name=node_name, content=[Comp.Plain(first_node_text)])]
        local_paths: list[str] = []
        for index, media in enumerate(post.media[:max_media], start=1):
            component = None
            if download_media:
                local_path = await self._download_media(media, post.post_id or "post", index)
                if local_path:
                    local_paths.append(local_path)
                    component = self._component_from_local(local_path, media.kind)
            if component is None:
                component = self._component_from_url(media.url, media.kind)
            chain.append(component)
            forward_nodes.append(Comp.Node(uin=node_uin, name=node_name, content=[component]))

        if use_forward and len(forward_nodes) > 1:
            return [Comp.Nodes(forward_nodes)], local_paths
        return chain, local_paths

    @staticmethod
    def _format_template(template: str, **values: Any) -> str:
        try:
            return template.format(**values)
        except Exception:
            return str(values.get("title") or values.get("ai_name") or "鸣潮 COS")

    async def _download_media(self, media: MediaItem, post_id: str, index: int) -> str | None:
        timeout = float(_get_config_value(self.config, "download_timeout", 25.0))
        suffix = _url_suffix(media.url)
        if suffix not in MEDIA_EXTENSIONS:
            suffix = ".jpg" if media.kind == "image" else ".mp4"
        safe_post_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", post_id)[:80] or "post"
        target_dir = self.output_dir / time.strftime("%Y%m%d_%H%M%S")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{safe_post_id}_{index}_{random.randint(1000, 9999)}{suffix}"

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
                response = await client.get(media.url)
                response.raise_for_status()
                target.write_bytes(response.content)
            return str(target)
        except Exception as exc:
            logger.warning(f"[kuro_cos] 下载媒体失败：{media.url} {exc!r}")
            return None

    def _component_from_local(self, path: str, kind: str) -> Any:
        if kind == "image":
            return Comp.Image.fromFileSystem(path)
        video_cls = getattr(Comp, "Video", None)
        if video_cls and hasattr(video_cls, "fromFileSystem"):
            return video_cls.fromFileSystem(path)
        file_cls = getattr(Comp, "File", None)
        if file_cls and hasattr(file_cls, "fromFileSystem"):
            return file_cls.fromFileSystem(path)
        return Comp.Plain(f"\n视频：{path}")

    def _component_from_url(self, url: str, kind: str) -> Any:
        if kind == "image":
            try:
                return Comp.Image.fromURL(url)
            except Exception:
                return Comp.Plain(f"\n图片：{url}")
        video_cls = getattr(Comp, "Video", None)
        if video_cls and hasattr(video_cls, "fromURL"):
            return video_cls.fromURL(url)
        return Comp.Plain(f"\n视频：{url}")

    def _remember_post(self, post: KuroPost):
        key = post.post_id or post.url or post.title
        if key:
            self._recent_post_ids.append(key)

    def _cleanup_local_files(self, paths: list[str]):
        cleaned_dirs: set[Path] = set()
        for path_text in paths:
            path = Path(path_text)
            try:
                if path.is_file():
                    cleaned_dirs.add(path.parent)
                    path.unlink()
            except Exception as exc:
                logger.warning(f"[kuro_cos] 删除本地媒体失败：{path} {exc!r}")
        for directory in cleaned_dirs:
            try:
                directory.rmdir()
            except OSError:
                pass

    def _debug(self, message: str):
        if bool(_get_config_value(self.config, "debug_log", False)):
            logger.info(f"[kuro_cos] {message}")