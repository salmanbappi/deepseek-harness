# Agent Note：DeepSeek 适配器的部署请求头

Status: implemented

[English](2026-09-13-deepseek-deployment-request-headers.md) | 中文

## Problem

部分 OpenAI 兼容网关只接纳它已识别的客户端，对其它任何 `User-Agent` 一律返回 HTTP 401，因此部署无法访问这些网关背后的模型。AgentRouter 就是其中之一：`deepseek-harness/<version> (+<url>)` 与 `curl` 都收到 401 `unauthorized client detected`，而 `cline/3.5.0` 收到 200。`dsh-llm-pi-ai` 的 provider profile 早已为此携带 `headers` 映射；`dsh-llm-deepseek` 没有对应能力，因此 `deepseek-official` 路由无法指向这类网关，该路由为其目录声明的 in-history 系统提示词能力也被挡在网关之后。

## Decision

`dsh-llm-deepseek` 接受 `headers`——由部署拥有的额外请求头映射——作为经校验的配置字段，而不是硬编码常量。

### 合并与归属

`@deepseek-ai/dsh-llm` 中的 `requestHeaders` 把 `attributionHeaders()` 与该映射合并：按字段名让映射胜出，并丢弃映射以另一种大小写重述的 attribution 拼写。只接纳单一客户端的网关，既拒绝以逗号合并的 `User-Agent`，也拒绝下游归一化器碰巧保留的任一份值。凭据、`content-type`、`accept` 与 `x-deepseek-harness-*` 头在合并之后写入，始终归 harness 所有，因此部署无法替换 API key 或请求身份。`dsh-llm-pi-ai` 改为调用同一 helper，不再保留自己的相同副本。

### 校验

`resolveAdapterOptions` 在加载时以及每个设置快照上判断该映射：头名必须是 RFC 9110 的 `tchar`，值不得包含 CR、LF 或 NUL；同一字段名的两种拼写会被拒绝，因为 HTTP 字段名大小写不敏感，合并后的值既不是部署想要的那一个，也不代表另一个。空映射解析为「无此事实」，因此空配置节不会改变快照身份。该映射经 `DeepSeekConnectionOptions.headers` 与 `DeepSeekFileConnection.headers` 同时作用于聊天请求与 Files API。

### 归因

[强制归因决策](../architecture/2026-06-21-mandatory-app-attribution-headers.zh.md)拥有默认值，且该默认值仍然成立：未配置任何头的部署在每个提供方请求上发送 harness 的 `User-Agent`。重述 `User-Agent` 的部署会替换它——这正是 `dsh-llm-pi-ai` 已交付的规则：只接纳单一客户端的网关既拒绝合并后的值，也拒绝它不认可的值，因此保留该名称会让每个按客户端准入的网关都无法经此路由访问。`requestHeaders` 是该规则的唯一归属，两个适配器都调用它。

## Alternatives considered

**只提供 `userAgent` 字段。** 能覆盖已观察到的拒绝情形，但网关还会要求租户、客户端或链路追踪头，该字段无法表达，而 pi-ai 已经公开了通用映射。

**为部署接入 `AppIdentity`。** 其渲染结果为 `product/version (+url)`，无法产出该网关接纳的确切值 `cline/3.5.0`；它能表达的仍然只是套着别的版本号的 harness 产品标识。

**为归因保留 `user-agent`。** 身份保持无条件，但会让每个按客户端准入的网关都无法经此路由访问，而正是这一部署场景催生了该字段。

**在包内复制 pi-ai 的 helper。** 同一条合并规则的两份副本会漂移；该 helper 应与其所合并的 attribution 放在一起。

## Consequences

- 部署可自行获准进入按客户端准入的网关，并为其出示的身份负责；网关不认可的值会表现为提供方错误，适配器一侧没有线索。
- 该映射是纯字符串。存入其中的凭据位于凭据 seam 之外，不会被排序、轮换或脱敏；密钥应存为 `apiKeyEnv` 引用。
- 上传文件复用按端点与 API key 划定作用域，因此仅在头上不同的两个部署会共享彼此的上传文件映射。
- 重写或重排请求头的网关会静默改变线上请求；唯一信号是提供方自身的错误。

## Testing

- `packages/llm/llm-deepseek/tests/adapter.spec.ts` 在 mock server 上断言合并后的聊天头、与其并列的 harness 自有头，以及每种拒绝：非法名称、含 LF 的值、同一名称的两种拼写，和空映射解析为无此事实。
- `packages/llm/llm-deepseek/tests/files-api.spec.ts` 与 `tests/file-store.spec.ts` 在文件传输上断言同一映射，含从 connection 到 client 的传递路径。
- `docs/config-catalog.md` 携带该字段及其 JSDoc；`pnpm run verify-config-catalog` 负责其新鲜度。
