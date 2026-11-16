# aa-ticket 升级到 0.3.0（树莓派测试机）

适用于：已经装了 **0.2.0** 的 AA。还是 0.1.0 的话，先按 `install-raspberry-pi.zh-hans.md` 里「从 0.1.0 升级到 0.2.0」升到 0.2.0。

> 两种身份：
> - **你自己的账号**：能用 `sudo`，用来备份数据库、重启服务。
> - **`allianceserver`**：用 `sudo su allianceserver` 切换过去，用来装插件、执行 `manage.py`；输入 `exit` 回到自己的账号。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-0.3.0-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：**

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-0.3.0-*
```

能看到文件，大小不是 0。

---

## 第 2 步：安装新版本

**在哪里做：** 切换到 `allianceserver`，**先 `cd ~`**。

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
pip install -U "git+https://github.com/yilifaer/aa-ticket.git@claude/friendly-einstein-21gzh0"
```

**做完怎么确认：**

```bash
pip show aa-ticket | head -2
pip show allianceauth | head -2
```

- `aa-ticket` 显示 `0.3.0`；
- `allianceauth` 仍然是 `5.4.0`。

---

## 第 3 步：更新数据库、收集静态文件

**在哪里做：** 还是 `allianceserver`。

```bash
cd /home/allianceserver/myauth
python manage.py migrate
python manage.py collectstatic --noinput
```

**做完怎么确认：** `migrate` 输出里有 `Applying aa_ticket.0004_priority_is_urgent... OK`。

---

## 第 4 步：重启

```bash
exit
sudo supervisorctl restart myauth:
sudo supervisorctl status
```

**做完怎么确认：** 所有 `myauth:` 开头的进程都是 `RUNNING`。

---

## 第 5 步：检查新功能

| # | 做什么 | 应该看到 |
|---|---|---|
| 1 | 用 Sally（Diplo 普通负责人）点左侧「工单」 | 第一页是「总览」，依次有四块：分配给我的、我的部门待接手、上报或邀请我部门的、我提交的工单 |
| 2 | 看「我的部门待接手」 | 紧急的工单排在最前面，每行有「接手」按钮；点「接手」后进入工单详情 |
| 3 | 某一块没有工单 | 只显示一行字（比如「没有待接手的工单。」），不是空表格 |
| 4 | 每块标题旁 | 有总数；工单超过 5 张时只列 5 张，点「查看全部」跳到工作台对应标签 |
| 5 | 用一个普通成员（不在任何部门组）点「工单」 | 只看到「我提交的工单」一块，「等你回复」的排在前面，顶部有「提交工单」按钮 |
| 6 | 打开 AA 首页（Dashboard） | 有「工单」卡片：我的未关闭工单数、等你回复数；部门人员还有分配给我的、待接手数；有紧急待接手时显示红色提示 |
| 7 | 用一个没有任何未关闭工单、也不是部门人员的号打开 AA 首页 | 没有「工单」卡片（正常） |
| 8 | 管理 → 紧急程度 | 多了「紧急」一列，Urgent 那一档是「是」；编辑档位时有「算作紧急」开关 |
| 9 | 管理 → 部门（深色主题） | 警告文字是正常颜色，前面有黄色或红色小图标，能看清 |
| 10 | 管理 → 部门 | 停用的部门折叠在列表下方的「已停用（N）」里，点开才显示 |
| 11 | 用 yilifaerr（有「查看并处理所有工单」权限）看总览 | 只显示他所在部门的内容，不会把全联盟的工单都列出来；全部工单仍在工作台 |

> 第 8 条：如果你们把紧急那一档改过名字，升级时会自动把排序最高的那一档设为紧急。不对的话，在「管理 → 紧急程度」里自己改。

哪一条不对，记下编号、看到的现象和截图发给我（截图里不要带 webhook 地址）。

---

## 出问题时退回 0.2.0（保留所有工单）

**不要**用安装文档里「出问题时怎么回滚」的办法，那会删掉所有工单。按下面做：

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
cd /home/allianceserver/myauth
python manage.py migrate aa_ticket 0003
cd ~
pip install --force-reinstall --no-deps "git+https://github.com/yilifaer/aa-ticket.git@ade5fa0"
cd /home/allianceserver/myauth
python manage.py collectstatic --noinput
exit
sudo supervisorctl restart myauth:
```

**做完怎么确认：** `pip show aa-ticket` 显示 `0.2.0`，工单都还在。
