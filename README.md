# AstrBot 鸣潮库街区 COS 搬运插件

从鸣潮库街区 COS 板块随机获取帖子，只提取帖子正文里的 COS 图片/视频，然后让机器人发送到当前聊天。

## 使用方法

固定命令：

```text
鸣潮cos
```

不需要加 `/`。插件只保留这个固定命令，不支持在配置中自定义触发词。

## 安装

把 `astrbot_plugin_kuro_cos` 文件夹放入 AstrBot 插件目录，然后安装依赖：

```bash
pip install -r requirements.txt
```

## 当前策略

- 只请求库街区 COS 板块：`gameId=3`、`forumId=17`、`searchType=3`；
- 每次随机请求多页，默认从 `1~500` 页里抽 `8` 页；
- 每页默认取 `5` 条，组合成候选池后随机挑选；
- 记住最近发过的帖子，降低连续重复概率；
- 只读取帖子正文媒体字段：`imgContent`、图片列表、视频字段、正文直链；
- 不再扫描整条帖子 JSON，所以不会把用户头像、头像框、等级图标抓出来；
- 默认下载到本地后发送，发送后自动删除本地图片/视频；
- 默认使用合并转发发送整条帖子，可在控制台关闭。

## 配置重点

- `request_rounds`：一次随机请求多少页，越大越不容易重复；
- `random_page_max`：随机页码上限；
- `default_page_size`：每页取多少条帖子；
- `max_media_per_post`：单条帖子最多发送多少个正文媒体；
- `download_media`：是否先下载媒体再发；
- `use_forward`：是否使用合并转发发送帖子内容，默认开启；
- `forward_sender_name`：合并转发节点显示的发送者昵称；
- `forward_sender_id`：合并转发节点显示的发送者 QQ/ID；
- `delete_after_send`：发送后是否自动删除本地媒体；
- `forum_id`：鸣潮 COS 板块 ID，默认 `17`。

如果还是重复，把 `request_rounds` 和 `default_page_size` 调大。